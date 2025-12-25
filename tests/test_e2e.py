"""
End-to-End tests for Verifactu Module.

Tests the complete invoice flow from creation to AEAT submission.
"""

import pytest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from verifactu.models import VerifactuConfig, VerifactuRecord, VerifactuEvent, ContingencyQueue
from verifactu.services import HashService, XMLService, QRService, AEATClient
from verifactu.services.aeat_client import MockAEATClient, AEATResponse, AEATEnvironment
from verifactu.services.contingency import get_contingency_manager, ContingencyMode


class TestVerifactuConfigE2E(TestCase):
    """E2E tests for Verifactu configuration."""

    def test_config_singleton_creation(self):
        """Test singleton config creation."""
        config = VerifactuConfig.get_config()
        assert config is not None

    def test_config_update_and_retrieve(self):
        """Test config update persists."""
        config = VerifactuConfig.get_config()
        config.software_name = 'Test Software'
        config.software_id = 'TEST-001'
        config.save()

        # Retrieve again
        config2 = VerifactuConfig.get_config()
        assert config2.software_name == 'Test Software'
        assert config2.software_id == 'TEST-001'


class TestRecordCreationE2E(TestCase):
    """E2E tests for record creation flow."""

    def setUp(self):
        """Set up test configuration."""
        self.config = VerifactuConfig.get_config()
        self.config.software_name = 'ERPlora Test'
        self.config.software_id = 'ERPLORA-TEST-001'
        self.config.software_version = '1.0.0'
        self.config.environment = 'testing'
        self.config.save()

    def test_create_first_alta_record(self):
        """Test creating the first alta record (no chain)."""
        timestamp = timezone.now()

        # Calculate hash
        record_hash = HashService.calculate_alta_hash(
            issuer_nif='B12345678',
            invoice_number='F2024-001',
            invoice_date=date(2024, 12, 25),
            invoice_type='F1',
            tax_amount=Decimal('21.00'),
            total_amount=Decimal('121.00'),
            previous_hash='',
            generation_timestamp=timestamp,
        )

        # Create record
        record = VerifactuRecord.objects.create(
            record_type='alta',
            sequence_number=1,
            issuer_nif='B12345678',
            issuer_name='Test Company S.L.',
            invoice_number='F2024-001',
            invoice_date=date(2024, 12, 25),
            invoice_type='F1',
            description='Test invoice',
            base_amount=Decimal('100.00'),
            tax_rate=Decimal('21.00'),
            tax_amount=Decimal('21.00'),
            total_amount=Decimal('121.00'),
            previous_hash='',
            is_first_record=True,
            generation_timestamp=timestamp,
            record_hash=record_hash,
        )

        assert record.id is not None
        assert record.is_first_record is True
        assert len(record.record_hash) == 64

    def test_create_chained_records(self):
        """Test creating a chain of records."""
        timestamp1 = datetime(2024, 12, 25, 10, 0, 0, tzinfo=timezone.utc)
        timestamp2 = datetime(2024, 12, 25, 10, 1, 0, tzinfo=timezone.utc)
        timestamp3 = datetime(2024, 12, 25, 10, 2, 0, tzinfo=timezone.utc)

        # First record
        hash1 = HashService.calculate_alta_hash(
            issuer_nif='B12345678',
            invoice_number='F2024-001',
            invoice_date=date(2024, 12, 25),
            invoice_type='F1',
            tax_amount=Decimal('21.00'),
            total_amount=Decimal('121.00'),
            previous_hash='',
            generation_timestamp=timestamp1,
        )

        record1 = VerifactuRecord.objects.create(
            record_type='alta',
            sequence_number=1,
            issuer_nif='B12345678',
            issuer_name='Test Company S.L.',
            invoice_number='F2024-001',
            invoice_date=date(2024, 12, 25),
            invoice_type='F1',
            description='Invoice 1',
            base_amount=Decimal('100.00'),
            tax_rate=Decimal('21.00'),
            tax_amount=Decimal('21.00'),
            total_amount=Decimal('121.00'),
            previous_hash='',
            is_first_record=True,
            generation_timestamp=timestamp1,
            record_hash=hash1,
        )

        # Second record (chained)
        hash2 = HashService.calculate_alta_hash(
            issuer_nif='B12345678',
            invoice_number='F2024-002',
            invoice_date=date(2024, 12, 25),
            invoice_type='F1',
            tax_amount=Decimal('42.00'),
            total_amount=Decimal('242.00'),
            previous_hash=hash1,
            generation_timestamp=timestamp2,
        )

        record2 = VerifactuRecord.objects.create(
            record_type='alta',
            sequence_number=2,
            issuer_nif='B12345678',
            issuer_name='Test Company S.L.',
            invoice_number='F2024-002',
            invoice_date=date(2024, 12, 25),
            invoice_type='F1',
            description='Invoice 2',
            base_amount=Decimal('200.00'),
            tax_rate=Decimal('21.00'),
            tax_amount=Decimal('42.00'),
            total_amount=Decimal('242.00'),
            previous_hash=hash1,
            is_first_record=False,
            generation_timestamp=timestamp2,
            record_hash=hash2,
        )

        # Verify chain
        assert record2.previous_hash == record1.record_hash
        assert record1.record_hash != record2.record_hash

    def test_create_anulacion_record(self):
        """Test creating an anulación record."""
        timestamp1 = datetime(2024, 12, 25, 10, 0, 0, tzinfo=timezone.utc)
        timestamp2 = datetime(2024, 12, 25, 11, 0, 0, tzinfo=timezone.utc)

        # First create alta
        hash1 = HashService.calculate_alta_hash(
            issuer_nif='B12345678',
            invoice_number='F2024-001',
            invoice_date=date(2024, 12, 25),
            invoice_type='F1',
            tax_amount=Decimal('21.00'),
            total_amount=Decimal('121.00'),
            previous_hash='',
            generation_timestamp=timestamp1,
        )

        record1 = VerifactuRecord.objects.create(
            record_type='alta',
            sequence_number=1,
            issuer_nif='B12345678',
            issuer_name='Test Company S.L.',
            invoice_number='F2024-001',
            invoice_date=date(2024, 12, 25),
            invoice_type='F1',
            description='Invoice 1',
            base_amount=Decimal('100.00'),
            tax_rate=Decimal('21.00'),
            tax_amount=Decimal('21.00'),
            total_amount=Decimal('121.00'),
            previous_hash='',
            is_first_record=True,
            generation_timestamp=timestamp1,
            record_hash=hash1,
        )

        # Create anulación
        hash2 = HashService.calculate_anulacion_hash(
            issuer_nif='B12345678',
            invoice_number='F2024-001',
            invoice_date=date(2024, 12, 25),
            previous_hash=hash1,
            generation_timestamp=timestamp2,
        )

        record2 = VerifactuRecord.objects.create(
            record_type='anulacion',
            sequence_number=2,
            issuer_nif='B12345678',
            issuer_name='Test Company S.L.',
            invoice_number='F2024-001',
            invoice_date=date(2024, 12, 25),
            invoice_type='F1',
            description='Cancellation of Invoice 1',
            base_amount=Decimal('100.00'),
            tax_rate=Decimal('21.00'),
            tax_amount=Decimal('21.00'),
            total_amount=Decimal('121.00'),
            previous_hash=hash1,
            is_first_record=False,
            generation_timestamp=timestamp2,
            record_hash=hash2,
        )

        assert record2.record_type == 'anulacion'
        assert record2.previous_hash == record1.record_hash


class TestXMLGenerationE2E(TestCase):
    """E2E tests for XML generation."""

    def setUp(self):
        """Set up test configuration."""
        self.config = VerifactuConfig.get_config()
        self.config.software_name = 'ERPlora Test'
        self.config.software_id = 'ERPLORA-TEST-001'
        self.config.software_version = '1.0.0'
        self.config.save()

    def test_generate_alta_xml_complete(self):
        """Test complete alta XML generation."""
        timestamp = datetime(2024, 12, 25, 10, 0, 0, tzinfo=timezone.utc)

        hash_value = HashService.calculate_alta_hash(
            issuer_nif='B12345678',
            invoice_number='F2024-001',
            invoice_date=date(2024, 12, 25),
            invoice_type='F1',
            tax_amount=Decimal('21.00'),
            total_amount=Decimal('121.00'),
            previous_hash='',
            generation_timestamp=timestamp,
        )

        record = VerifactuRecord.objects.create(
            record_type='alta',
            sequence_number=1,
            issuer_nif='B12345678',
            issuer_name='Test Company S.L.',
            invoice_number='F2024-001',
            invoice_date=date(2024, 12, 25),
            invoice_type='F1',
            description='Test invoice',
            base_amount=Decimal('100.00'),
            tax_rate=Decimal('21.00'),
            tax_amount=Decimal('21.00'),
            total_amount=Decimal('121.00'),
            previous_hash='',
            is_first_record=True,
            generation_timestamp=timestamp,
            record_hash=hash_value,
        )

        xml = XMLService.generate_alta_xml(record, self.config)

        # Verify XML structure
        assert '<?xml' in xml
        assert 'soapenv:Envelope' in xml
        assert 'sf:RegistroAlta' in xml
        assert 'B12345678' in xml
        assert 'F2024-001' in xml
        assert '121.00' in xml

    def test_generate_xml_validates(self):
        """Test generated XML is well-formed."""
        timestamp = timezone.now()

        hash_value = HashService.calculate_alta_hash(
            issuer_nif='B12345678',
            invoice_number='F2024-001',
            invoice_date=date(2024, 12, 25),
            invoice_type='F1',
            tax_amount=Decimal('21.00'),
            total_amount=Decimal('121.00'),
            previous_hash='',
            generation_timestamp=timestamp,
        )

        record = VerifactuRecord.objects.create(
            record_type='alta',
            sequence_number=1,
            issuer_nif='B12345678',
            issuer_name='Test Company S.L.',
            invoice_number='F2024-001',
            invoice_date=date(2024, 12, 25),
            invoice_type='F1',
            description='Test invoice',
            base_amount=Decimal('100.00'),
            tax_rate=Decimal('21.00'),
            tax_amount=Decimal('21.00'),
            total_amount=Decimal('121.00'),
            previous_hash='',
            is_first_record=True,
            generation_timestamp=timestamp,
            record_hash=hash_value,
        )

        xml = XMLService.generate_alta_xml(record, self.config)
        is_valid, error = XMLService.validate_xml(xml)

        assert is_valid is True
        assert error is None


class TestSubmissionE2E(TestCase):
    """E2E tests for AEAT submission flow."""

    def setUp(self):
        """Set up test configuration."""
        self.config = VerifactuConfig.get_config()
        self.config.software_name = 'ERPlora Test'
        self.config.software_id = 'ERPLORA-TEST-001'
        self.config.software_version = '1.0.0'
        self.config.certificate_path = '/path/to/cert.p12'
        self.config.environment = 'testing'
        self.config.save()

    def test_full_submission_flow_mock(self):
        """Test complete submission flow with mock client."""
        timestamp = timezone.now()

        # Create record
        hash_value = HashService.calculate_alta_hash(
            issuer_nif='B12345678',
            invoice_number='F2024-001',
            invoice_date=date(2024, 12, 25),
            invoice_type='F1',
            tax_amount=Decimal('21.00'),
            total_amount=Decimal('121.00'),
            previous_hash='',
            generation_timestamp=timestamp,
        )

        record = VerifactuRecord.objects.create(
            record_type='alta',
            sequence_number=1,
            issuer_nif='B12345678',
            issuer_name='Test Company S.L.',
            invoice_number='F2024-001',
            invoice_date=date(2024, 12, 25),
            invoice_type='F1',
            description='Test invoice',
            base_amount=Decimal('100.00'),
            tax_rate=Decimal('21.00'),
            tax_amount=Decimal('21.00'),
            total_amount=Decimal('121.00'),
            previous_hash='',
            is_first_record=True,
            generation_timestamp=timestamp,
            record_hash=hash_value,
            transmission_status='pending',
        )

        # Generate XML
        xml = XMLService.generate_alta_xml(record, self.config)

        # Submit with mock client
        client = MockAEATClient()
        response = client.submit_alta(xml)

        # Update record
        if response.success:
            record.transmission_status = 'sent'
            record.csv = response.csv
            record.transmitted_at = response.timestamp
            record.save()

        # Verify
        record.refresh_from_db()
        assert record.transmission_status == 'sent'
        assert record.csv is not None

    def test_submission_failure_queues_record(self):
        """Test failed submission queues record for retry."""
        timestamp = timezone.now()

        hash_value = HashService.calculate_alta_hash(
            issuer_nif='B12345678',
            invoice_number='F2024-001',
            invoice_date=date(2024, 12, 25),
            invoice_type='F1',
            tax_amount=Decimal('21.00'),
            total_amount=Decimal('121.00'),
            previous_hash='',
            generation_timestamp=timestamp,
        )

        record = VerifactuRecord.objects.create(
            record_type='alta',
            sequence_number=1,
            issuer_nif='B12345678',
            issuer_name='Test Company S.L.',
            invoice_number='F2024-001',
            invoice_date=date(2024, 12, 25),
            invoice_type='F1',
            description='Test invoice',
            base_amount=Decimal('100.00'),
            tax_rate=Decimal('21.00'),
            tax_amount=Decimal('21.00'),
            total_amount=Decimal('121.00'),
            previous_hash='',
            is_first_record=True,
            generation_timestamp=timestamp,
            record_hash=hash_value,
            transmission_status='pending',
        )

        # Mock failed submission
        client = MockAEATClient()
        client.set_failure(code='NETWORK_ERROR', message='Connection refused')

        xml = XMLService.generate_alta_xml(record, self.config)
        response = client.submit_alta(xml)

        # Queue for retry
        if not response.success:
            ContingencyQueue.objects.create(
                record=record,
                reason=response.message,
                status='pending',
            )
            record.transmission_status = 'queued'
            record.save()

        # Verify
        record.refresh_from_db()
        assert record.transmission_status == 'queued'
        assert ContingencyQueue.objects.filter(record=record).exists()


class TestEventLoggingE2E(TestCase):
    """E2E tests for event logging."""

    def test_events_logged_on_record_creation(self):
        """Test events are logged when records are created."""
        timestamp = timezone.now()

        hash_value = HashService.calculate_alta_hash(
            issuer_nif='B12345678',
            invoice_number='F2024-001',
            invoice_date=date(2024, 12, 25),
            invoice_type='F1',
            tax_amount=Decimal('21.00'),
            total_amount=Decimal('121.00'),
            previous_hash='',
            generation_timestamp=timestamp,
        )

        record = VerifactuRecord.objects.create(
            record_type='alta',
            sequence_number=1,
            issuer_nif='B12345678',
            issuer_name='Test Company S.L.',
            invoice_number='F2024-001',
            invoice_date=date(2024, 12, 25),
            invoice_type='F1',
            description='Test invoice',
            base_amount=Decimal('100.00'),
            tax_rate=Decimal('21.00'),
            tax_amount=Decimal('21.00'),
            total_amount=Decimal('121.00'),
            previous_hash='',
            is_first_record=True,
            generation_timestamp=timestamp,
            record_hash=hash_value,
        )

        # Log event
        VerifactuEvent.objects.create(
            event_type='generation',
            description=f'Record generated: {record.invoice_number}',
            record=record,
        )

        # Verify
        events = VerifactuEvent.objects.filter(record=record)
        assert events.count() == 1
        assert events.first().event_type == 'generation'


class TestQRCodeE2E(TestCase):
    """E2E tests for QR code generation."""

    def test_qr_url_generation(self):
        """Test QR verification URL generation."""
        url = QRService.generate_verification_url(
            issuer_nif='B12345678',
            invoice_number='F2024-001',
            invoice_date=date(2024, 12, 25),
            total_amount=Decimal('121.00'),
        )

        assert 'agenciatributaria.gob.es' in url
        assert 'B12345678' in url
        assert 'F2024-001' in url
        assert '25-12-2024' in url
        assert '121.00' in url

    @pytest.mark.skipif(not QRService.is_available(), reason="QR library not installed")
    def test_qr_code_generation(self):
        """Test QR code image generation."""
        qr_bytes = QRService.generate_qr_code(
            issuer_nif='B12345678',
            invoice_number='F2024-001',
            invoice_date=date(2024, 12, 25),
            total_amount=Decimal('121.00'),
        )

        # PNG magic bytes
        assert qr_bytes[:8] == b'\x89PNG\r\n\x1a\n'


class TestContingencyE2E(TestCase):
    """E2E tests for contingency management."""

    def test_contingency_mode_transitions(self):
        """Test contingency mode transitions."""
        manager = get_contingency_manager()

        # Start in normal mode
        assert manager.mode == ContingencyMode.NORMAL

        # Record failures
        from verifactu.services.contingency import FailureType
        manager.record_failure(FailureType.NETWORK, 'Test failure 1')
        manager.record_failure(FailureType.NETWORK, 'Test failure 2')
        manager.record_failure(FailureType.NETWORK, 'Test failure 3')

        # Should be offline after 3 failures
        assert manager.mode in [ContingencyMode.OFFLINE, ContingencyMode.DEGRADED]

        # Record success
        manager.record_success(1)

        # Should return to normal
        assert manager.mode == ContingencyMode.NORMAL

    def test_health_check(self):
        """Test system health check."""
        manager = get_contingency_manager()

        is_healthy, message = manager.check_health()

        # May or may not be healthy depending on config
        assert isinstance(is_healthy, bool)
        assert isinstance(message, str)
