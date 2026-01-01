"""
Tests for Verifactu models.

Tests cover:
- VerifactuConfig: Singleton behavior, mode locking, protection
- VerifactuRecord: Hash calculation, QR generation, chain integrity
- VerifactuEvent: Event logging
- ContingencyQueue: Queue management, retry scheduling
"""

import pytest
from datetime import date, timedelta
from decimal import Decimal
from django.utils import timezone
from django.core.exceptions import ValidationError

from verifactu.models import (
    VerifactuConfig, VerifactuRecord, VerifactuEvent, ContingencyQueue
)


@pytest.mark.django_db
class TestVerifactuConfig:
    """Tests for VerifactuConfig model."""

    def test_singleton_creation(self):
        """Test that config is a singleton."""
        config1 = VerifactuConfig.get_config()
        config2 = VerifactuConfig.get_config()

        assert config1.pk == config2.pk == 1

    def test_singleton_save_always_pk_1(self):
        """Test that save always uses pk=1."""
        config = VerifactuConfig()
        config.software_name = 'Test'
        config.save()

        assert config.pk == 1

    def test_default_values(self):
        """Test default configuration values."""
        config = VerifactuConfig.get_config()

        assert config.enabled is False
        assert config.mode == VerifactuConfig.Mode.VERIFACTU
        assert config.environment == VerifactuConfig.Environment.TESTING
        assert config.software_name == 'ERPlora Hub'
        assert config.auto_transmit is True
        assert config.retry_interval_minutes == 5
        assert config.max_retries == 10
        assert config.mode_locked is False

    def test_is_production_property(self):
        """Test is_production property."""
        config = VerifactuConfig.get_config()

        config.environment = VerifactuConfig.Environment.TESTING
        assert config.is_production is False

        config.environment = VerifactuConfig.Environment.PRODUCTION
        assert config.is_production is True

    def test_is_verifactu_mode_property(self):
        """Test is_verifactu_mode property."""
        config = VerifactuConfig.get_config()

        config.mode = VerifactuConfig.Mode.VERIFACTU
        assert config.is_verifactu_mode is True

        config.mode = VerifactuConfig.Mode.NO_VERIFACTU
        assert config.is_verifactu_mode is False

    def test_aeat_endpoint_testing(self):
        """Test AEAT endpoint for testing environment."""
        config = VerifactuConfig.get_config()
        config.environment = VerifactuConfig.Environment.TESTING

        assert 'prewww1.aeat.es' in config.aeat_endpoint

    def test_aeat_endpoint_production(self):
        """Test AEAT endpoint for production environment."""
        config = VerifactuConfig.get_config()
        config.environment = VerifactuConfig.Environment.PRODUCTION

        assert 'www1.agenciatributaria.gob.es' in config.aeat_endpoint

    def test_days_until_certificate_expiry(self):
        """Test certificate expiry calculation."""
        config = VerifactuConfig.get_config()

        # No certificate
        assert config.days_until_certificate_expiry() is None

        # Certificate expiring in 30 days
        config.certificate_expiry = timezone.now().date() + timedelta(days=30)
        assert config.days_until_certificate_expiry() == 30

        # Certificate expired
        config.certificate_expiry = timezone.now().date() - timedelta(days=5)
        assert config.days_until_certificate_expiry() == -5

    def test_can_change_mode_not_locked(self):
        """Test mode can be changed when not locked."""
        config = VerifactuConfig.get_config()
        config.mode_locked = False

        assert config.can_change_mode() is True

    def test_can_change_mode_locked_current_year(self):
        """Test mode cannot be changed when locked for current year."""
        config = VerifactuConfig.get_config()
        config.mode_locked = True
        config.fiscal_year_locked = timezone.now().year

        assert config.can_change_mode() is False

    def test_can_change_mode_locked_different_year(self):
        """Test mode can be changed when locked for different year."""
        config = VerifactuConfig.get_config()
        config.mode_locked = True
        config.fiscal_year_locked = timezone.now().year - 1

        assert config.can_change_mode() is True

    def test_lock_mode(self):
        """Test mode locking."""
        config = VerifactuConfig.get_config()
        config.mode_locked = False
        config.save()

        import uuid
        user_id = uuid.uuid4()
        config.lock_mode(user_id=user_id)

        config.refresh_from_db()
        assert config.mode_locked is True
        assert config.mode_locked_by == user_id
        assert config.fiscal_year_locked == timezone.now().year
        assert config.module_activated is True
        assert config.first_record_date == timezone.now().date()

    def test_lock_mode_already_locked(self):
        """Test locking already locked mode does nothing."""
        config = VerifactuConfig.get_config()
        config.mode_locked = True
        config.fiscal_year_locked = 2024
        config.save()

        config.lock_mode()

        # Should remain unchanged
        assert config.fiscal_year_locked == 2024

    def test_can_deactivate_module_not_activated(self):
        """Test module can be deactivated when not activated."""
        config = VerifactuConfig.get_config()
        config.module_activated = False
        config.save()

        # Ensure no records exist
        VerifactuRecord.objects.all().delete()

        assert config.can_deactivate_module() is True

    def test_can_deactivate_module_activated(self):
        """Test module cannot be deactivated when activated."""
        config = VerifactuConfig.get_config()
        config.module_activated = True
        config.save()

        assert config.can_deactivate_module() is False

    def test_str_representation(self):
        """Test string representation."""
        config = VerifactuConfig.get_config()
        config.mode = VerifactuConfig.Mode.VERIFACTU

        assert 'VERI*FACTU' in str(config)

    def test_get_mode_lock_info_not_locked(self):
        """Test mode lock info when not locked."""
        config = VerifactuConfig.get_config()
        config.mode_locked = False

        info = config.get_mode_lock_info()

        assert info['locked'] is False
        assert info['can_change'] is True


@pytest.mark.django_db
class TestVerifactuRecord:
    """Tests for VerifactuRecord model."""

    @pytest.fixture
    def sample_record_data(self):
        """Return sample record data."""
        return {
            'record_type': VerifactuRecord.RecordType.ALTA,
            'sequence_number': 1,
            'issuer_nif': 'B12345678',
            'issuer_name': 'Test Company S.L.',
            'invoice_number': 'F2024-001',
            'invoice_date': date(2024, 12, 25),
            'invoice_type': VerifactuRecord.InvoiceType.F1,
            'description': 'Test invoice',
            'base_amount': Decimal('100.00'),
            'tax_rate': Decimal('21.00'),
            'tax_amount': Decimal('21.00'),
            'total_amount': Decimal('121.00'),
            'previous_hash': '',
            'is_first_record': True,
            'generation_timestamp': timezone.now(),
        }

    def test_create_record(self, sample_record_data):
        """Test creating a Verifactu record."""
        record = VerifactuRecord.objects.create(**sample_record_data)

        assert record.id is not None
        assert record.record_type == VerifactuRecord.RecordType.ALTA
        assert record.issuer_nif == 'B12345678'
        assert record.total_amount == Decimal('121.00')

    def test_auto_hash_calculation(self, sample_record_data):
        """Test hash is auto-calculated on save."""
        record = VerifactuRecord.objects.create(**sample_record_data)

        assert record.record_hash is not None
        assert len(record.record_hash) == 64  # SHA-256 hex length

    def test_auto_qr_url_generation(self, sample_record_data):
        """Test QR URL is auto-generated on save."""
        record = VerifactuRecord.objects.create(**sample_record_data)

        assert record.qr_url is not None
        assert 'agenciatributaria.gob.es' in record.qr_url
        assert 'B12345678' in record.qr_url
        assert 'F2024-001' in record.qr_url

    def test_hash_includes_all_fields(self, sample_record_data):
        """Test hash changes when relevant fields change."""
        record1 = VerifactuRecord.objects.create(**sample_record_data)

        # Different invoice number should produce different hash
        sample_record_data['invoice_number'] = 'F2024-002'
        sample_record_data['sequence_number'] = 2
        record2 = VerifactuRecord.objects.create(**sample_record_data)

        assert record1.record_hash != record2.record_hash

    def test_calculate_hash_alta(self, sample_record_data):
        """Test hash calculation for alta record."""
        record = VerifactuRecord(**sample_record_data)
        hash_value = record.calculate_hash()

        assert len(hash_value) == 64
        assert hash_value.isupper()  # SHA-256 should be uppercase hex

    def test_calculate_hash_anulacion(self, sample_record_data):
        """Test hash calculation for anulación record."""
        sample_record_data['record_type'] = VerifactuRecord.RecordType.ANULACION
        record = VerifactuRecord(**sample_record_data)
        hash_value = record.calculate_hash()

        assert len(hash_value) == 64

    def test_generate_qr_url(self, sample_record_data):
        """Test QR URL generation."""
        record = VerifactuRecord(**sample_record_data)
        qr_url = record.generate_qr_url()

        assert 'nif=B12345678' in qr_url
        assert 'numserie=F2024-001' in qr_url
        assert 'fecha=25-12-2024' in qr_url
        assert 'importe=121.00' in qr_url

    def test_status_default_pending(self, sample_record_data):
        """Test default status is pending."""
        record = VerifactuRecord.objects.create(**sample_record_data)

        assert record.status == VerifactuRecord.TransmissionStatus.PENDING

    def test_str_representation(self, sample_record_data):
        """Test string representation."""
        record = VerifactuRecord.objects.create(**sample_record_data)

        assert 'F2024-001' in str(record)
        assert 'Alta' in str(record) or 'Registration' in str(record)

    def test_ordering_by_sequence(self, sample_record_data):
        """Test records are ordered by sequence number descending."""
        sample_record_data['sequence_number'] = 1
        record1 = VerifactuRecord.objects.create(**sample_record_data)

        sample_record_data['sequence_number'] = 2
        sample_record_data['invoice_number'] = 'F2024-002'
        record2 = VerifactuRecord.objects.create(**sample_record_data)

        records = list(VerifactuRecord.objects.all())
        assert records[0].sequence_number > records[1].sequence_number

    def test_invoice_types(self, sample_record_data):
        """Test all invoice types can be created."""
        for invoice_type in VerifactuRecord.InvoiceType:
            sample_record_data['invoice_type'] = invoice_type
            sample_record_data['sequence_number'] += 1
            sample_record_data['invoice_number'] = f'F2024-{invoice_type}'

            record = VerifactuRecord.objects.create(**sample_record_data)
            assert record.invoice_type == invoice_type


@pytest.mark.django_db
class TestVerifactuEvent:
    """Tests for VerifactuEvent model."""

    def test_create_event(self):
        """Test creating an event."""
        event = VerifactuEvent.objects.create(
            event_type=VerifactuEvent.EventType.RECORD_CREATED,
            severity=VerifactuEvent.Severity.INFO,
            message='Test event'
        )

        assert event.id is not None
        assert event.timestamp is not None

    def test_log_convenience_method(self):
        """Test log convenience method."""
        event = VerifactuEvent.log(
            event_type=VerifactuEvent.EventType.TRANSMISSION_SUCCESS,
            message='Record transmitted successfully',
            severity='info',
            csv='ABC123'
        )

        assert event.id is not None
        assert event.details.get('csv') == 'ABC123'

    def test_log_with_record(self):
        """Test logging event with related record."""
        record = VerifactuRecord.objects.create(
            record_type=VerifactuRecord.RecordType.ALTA,
            sequence_number=1,
            issuer_nif='B12345678',
            issuer_name='Test',
            invoice_number='F2024-001',
            invoice_date=date.today(),
            invoice_type=VerifactuRecord.InvoiceType.F1,
            base_amount=Decimal('100.00'),
            tax_amount=Decimal('21.00'),
            total_amount=Decimal('121.00'),
            generation_timestamp=timezone.now(),
        )

        event = VerifactuEvent.log(
            event_type=VerifactuEvent.EventType.RECORD_CREATED,
            message='Record created',
            record=record
        )

        assert event.record == record

    def test_event_types(self):
        """Test all event types."""
        for event_type in VerifactuEvent.EventType:
            event = VerifactuEvent.objects.create(
                event_type=event_type,
                message=f'Test {event_type}'
            )
            assert event.event_type == event_type

    def test_severity_levels(self):
        """Test all severity levels."""
        for severity in VerifactuEvent.Severity:
            event = VerifactuEvent.objects.create(
                event_type=VerifactuEvent.EventType.CONFIG_CHANGED,
                severity=severity,
                message=f'Test {severity}'
            )
            assert event.severity == severity

    def test_ordering_by_timestamp(self):
        """Test events are ordered by timestamp descending."""
        event1 = VerifactuEvent.objects.create(
            event_type=VerifactuEvent.EventType.CONFIG_CHANGED,
            message='Event 1'
        )
        event2 = VerifactuEvent.objects.create(
            event_type=VerifactuEvent.EventType.CONFIG_CHANGED,
            message='Event 2'
        )

        events = list(VerifactuEvent.objects.all())
        assert events[0].pk == event2.pk  # Most recent first

    def test_str_representation(self):
        """Test string representation."""
        event = VerifactuEvent.objects.create(
            event_type=VerifactuEvent.EventType.TRANSMISSION_SUCCESS,
            severity=VerifactuEvent.Severity.INFO,
            message='Success'
        )

        assert 'Info' in str(event)
        assert 'Transmission Success' in str(event) or 'transmission_success' in str(event).lower()


@pytest.mark.django_db
class TestContingencyQueue:
    """Tests for ContingencyQueue model."""

    @pytest.fixture
    def sample_record(self):
        """Create a sample record for queue tests."""
        return VerifactuRecord.objects.create(
            record_type=VerifactuRecord.RecordType.ALTA,
            sequence_number=1,
            issuer_nif='B12345678',
            issuer_name='Test',
            invoice_number='F2024-001',
            invoice_date=date.today(),
            invoice_type=VerifactuRecord.InvoiceType.F1,
            base_amount=Decimal('100.00'),
            tax_amount=Decimal('21.00'),
            total_amount=Decimal('121.00'),
            generation_timestamp=timezone.now(),
        )

    def test_create_queue_entry(self, sample_record):
        """Test creating a queue entry."""
        entry = ContingencyQueue.objects.create(
            record=sample_record,
            priority=ContingencyQueue.Priority.NORMAL
        )

        assert entry.id is not None
        assert entry.queued_at is not None
        assert entry.attempts == 0
        assert entry.status == ContingencyQueue.Status.PENDING

    def test_one_to_one_relationship(self, sample_record):
        """Test one-to-one relationship with record."""
        ContingencyQueue.objects.create(record=sample_record)

        # Should raise error if trying to create another entry for same record
        with pytest.raises(Exception):
            ContingencyQueue.objects.create(record=sample_record)

    def test_schedule_retry(self, sample_record):
        """Test retry scheduling with exponential backoff."""
        entry = ContingencyQueue.objects.create(
            record=sample_record,
            priority=ContingencyQueue.Priority.NORMAL
        )

        # First retry - 5 minutes
        entry.schedule_retry(interval_minutes=5)
        assert entry.attempts == 1
        assert entry.last_attempt_at is not None
        assert entry.next_attempt_at is not None

        # Second retry - 10 minutes
        entry.schedule_retry(interval_minutes=5)
        assert entry.attempts == 2

        # Third retry - 20 minutes
        entry.schedule_retry(interval_minutes=5)
        assert entry.attempts == 3

    def test_get_ready_for_retry(self, sample_record):
        """Test getting entries ready for retry."""
        entry = ContingencyQueue.objects.create(
            record=sample_record,
            priority=ContingencyQueue.Priority.NORMAL,
            next_attempt_at=timezone.now() - timedelta(minutes=1)  # Past
        )

        ready = ContingencyQueue.get_ready_for_retry()
        assert entry in ready

    def test_get_pending_count(self, sample_record):
        """Test pending count."""
        ContingencyQueue.objects.create(record=sample_record)

        assert ContingencyQueue.get_pending_count() == 1

    def test_priority_ordering(self):
        """Test queue entries are ordered by priority."""
        # Create records with different priorities
        record1 = VerifactuRecord.objects.create(
            record_type=VerifactuRecord.RecordType.ALTA,
            sequence_number=1,
            issuer_nif='B12345678',
            issuer_name='Test',
            invoice_number='F2024-001',
            invoice_date=date.today(),
            invoice_type=VerifactuRecord.InvoiceType.F1,
            base_amount=Decimal('100.00'),
            tax_amount=Decimal('21.00'),
            total_amount=Decimal('121.00'),
            generation_timestamp=timezone.now(),
        )
        record2 = VerifactuRecord.objects.create(
            record_type=VerifactuRecord.RecordType.ALTA,
            sequence_number=2,
            issuer_nif='B12345678',
            issuer_name='Test',
            invoice_number='F2024-002',
            invoice_date=date.today(),
            invoice_type=VerifactuRecord.InvoiceType.F1,
            base_amount=Decimal('100.00'),
            tax_amount=Decimal('21.00'),
            total_amount=Decimal('121.00'),
            generation_timestamp=timezone.now(),
        )

        entry_low = ContingencyQueue.objects.create(
            record=record1,
            priority=ContingencyQueue.Priority.LOW
        )
        entry_high = ContingencyQueue.objects.create(
            record=record2,
            priority=ContingencyQueue.Priority.HIGH
        )

        entries = list(ContingencyQueue.objects.all())
        assert entries[0].priority < entries[1].priority  # HIGH (1) before LOW (3)

    def test_str_representation(self, sample_record):
        """Test string representation."""
        entry = ContingencyQueue.objects.create(record=sample_record)
        entry.attempts = 3

        assert 'F2024-001' in str(entry)
        assert '#3' in str(entry)
