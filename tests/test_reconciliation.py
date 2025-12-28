"""
Tests for Verifactu Reconciliation Service.

Tests the reconciliation between local records and AEAT.
"""

import pytest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import Mock, patch, MagicMock

from verifactu.services.reconciliation_service import (
    ReconciliationService,
    ReconciliationResult,
    ReconciliationStatus,
    reconcile_on_certificate_config,
)
from verifactu.services.aeat_client import (
    AEATQueryResponse,
    AEATQueryRecord,
)


@pytest.fixture
def reconciliation_service():
    """Create reconciliation service instance."""
    return ReconciliationService()


@pytest.fixture
def mock_config():
    """Create mock VerifactuConfig."""
    config = Mock()
    config.certificate_path = '/path/to/cert.p12'
    config.certificate_password = 'test_password'
    config.software_nif = 'B12345678'
    config.is_production = False
    return config


@pytest.fixture
def mock_aeat_client():
    """Create mock AEAT client."""
    client = Mock()
    return client


class TestReconciliationResult:
    """Tests for ReconciliationResult dataclass."""

    def test_is_synced_when_success(self):
        """Test is_synced returns True for success status."""
        result = ReconciliationResult(
            status=ReconciliationStatus.SUCCESS,
            message="Synced",
        )
        assert result.is_synced is True

    def test_is_synced_when_mismatch(self):
        """Test is_synced returns False for mismatch status."""
        result = ReconciliationResult(
            status=ReconciliationStatus.MISMATCH_DETECTED,
            message="Mismatch",
        )
        assert result.is_synced is False

    def test_needs_attention_when_mismatch(self):
        """Test needs_attention returns True for mismatch."""
        result = ReconciliationResult(
            status=ReconciliationStatus.MISMATCH_DETECTED,
            message="Mismatch",
        )
        assert result.needs_attention is True

    def test_needs_attention_when_failed(self):
        """Test needs_attention returns True for failed."""
        result = ReconciliationResult(
            status=ReconciliationStatus.FAILED,
            message="Failed",
        )
        assert result.needs_attention is True

    def test_needs_attention_when_success(self):
        """Test needs_attention returns False for success."""
        result = ReconciliationResult(
            status=ReconciliationStatus.SUCCESS,
            message="Success",
        )
        assert result.needs_attention is False

    def test_default_values(self):
        """Test default values are set correctly."""
        result = ReconciliationResult(
            status=ReconciliationStatus.SUCCESS,
            message="Test",
        )
        assert result.discrepancies == []
        assert result.timestamp is not None
        assert result.local_last_hash is None
        assert result.aeat_last_hash is None


class TestReconciliationService:
    """Tests for ReconciliationService."""

    def test_has_certificate_when_configured(self, reconciliation_service):
        """Test has_certificate returns True when certificate is set."""
        with patch.object(
            reconciliation_service,
            '_get_config',
            return_value=Mock(
                certificate_path='/path/to/cert.p12',
                certificate_password='password',
            ),
        ):
            assert reconciliation_service.has_certificate() is True

    def test_has_certificate_when_not_configured(self, reconciliation_service):
        """Test has_certificate returns False when no certificate."""
        with patch.object(
            reconciliation_service,
            '_get_config',
            return_value=Mock(
                certificate_path='',
                certificate_password='',
            ),
        ):
            assert reconciliation_service.has_certificate() is False

    def test_has_certificate_partial_config(self, reconciliation_service):
        """Test has_certificate returns False with partial config."""
        with patch.object(
            reconciliation_service,
            '_get_config',
            return_value=Mock(
                certificate_path='/path/to/cert.p12',
                certificate_password='',  # Missing password
            ),
        ):
            assert reconciliation_service.has_certificate() is False

    def test_reconcile_no_certificate(self, reconciliation_service):
        """Test reconcile returns NO_CERTIFICATE when no cert."""
        with patch.object(
            reconciliation_service,
            'has_certificate',
            return_value=False,
        ):
            result = reconciliation_service.reconcile()

            assert result.status == ReconciliationStatus.NO_CERTIFICATE
            assert "certificado" in result.message.lower()

    @pytest.mark.django_db
    def test_reconcile_no_issuer_nif(self, reconciliation_service, mock_config):
        """Test reconcile fails when no issuer NIF configured."""
        mock_config.software_nif = ''

        with patch.object(
            reconciliation_service,
            'has_certificate',
            return_value=True,
        ), patch.object(
            reconciliation_service,
            '_get_config',
            return_value=mock_config,
        ):
            result = reconciliation_service.reconcile()

            assert result.status == ReconciliationStatus.FAILED
            assert "NIF" in result.message

    @pytest.mark.django_db
    def test_reconcile_aeat_unavailable(
        self,
        reconciliation_service,
        mock_config,
        mock_aeat_client,
    ):
        """Test reconcile handles AEAT unavailability."""
        mock_aeat_client.query_last_records.return_value = AEATQueryResponse(
            success=False,
            code='CONNECTION_ERROR',
            message='Connection failed',
        )

        with patch.object(
            reconciliation_service,
            'has_certificate',
            return_value=True,
        ), patch.object(
            reconciliation_service,
            '_get_config',
            return_value=mock_config,
        ), patch.object(
            reconciliation_service,
            '_get_aeat_client',
            return_value=mock_aeat_client,
        ), patch('verifactu.services.reconciliation_service.VerifactuRecord') as MockRecord:
            MockRecord.objects.filter.return_value.order_by.return_value.first.return_value = None
            MockRecord.objects.filter.return_value.count.return_value = 0

            result = reconciliation_service.reconcile()

            assert result.status == ReconciliationStatus.AEAT_UNAVAILABLE

    @pytest.mark.django_db
    def test_reconcile_chains_match(
        self,
        reconciliation_service,
        mock_config,
        mock_aeat_client,
    ):
        """Test reconcile returns SUCCESS when chains match."""
        test_hash = 'A' * 64

        # Mock local record
        mock_local_record = Mock()
        mock_local_record.record_hash = test_hash

        # Mock AEAT response
        mock_aeat_client.query_last_records.return_value = AEATQueryResponse(
            success=True,
            code='OK',
            message='Found 1 record',
            records=[
                AEATQueryRecord(
                    invoice_number='F2024-001',
                    invoice_date=date.today(),
                    record_type='alta',
                    record_hash=test_hash,
                    issuer_nif='B12345678',
                ),
            ],
            total_count=1,
        )

        with patch.object(
            reconciliation_service,
            'has_certificate',
            return_value=True,
        ), patch.object(
            reconciliation_service,
            '_get_config',
            return_value=mock_config,
        ), patch.object(
            reconciliation_service,
            '_get_aeat_client',
            return_value=mock_aeat_client,
        ), patch('verifactu.services.reconciliation_service.VerifactuRecord') as MockRecord:
            MockRecord.objects.filter.return_value.order_by.return_value.first.return_value = mock_local_record
            MockRecord.objects.filter.return_value.count.return_value = 1

            result = reconciliation_service.reconcile()

            assert result.status == ReconciliationStatus.SUCCESS
            assert result.local_last_hash == test_hash
            assert result.aeat_last_hash == test_hash
            assert result.is_synced is True

    @pytest.mark.django_db
    def test_reconcile_chains_mismatch(
        self,
        reconciliation_service,
        mock_config,
        mock_aeat_client,
    ):
        """Test reconcile detects mismatched chains."""
        local_hash = 'A' * 64
        aeat_hash = 'B' * 64

        # Mock local record
        mock_local_record = Mock()
        mock_local_record.record_hash = local_hash

        # Mock AEAT response with different hash
        mock_aeat_client.query_last_records.return_value = AEATQueryResponse(
            success=True,
            code='OK',
            message='Found 1 record',
            records=[
                AEATQueryRecord(
                    invoice_number='F2024-001',
                    invoice_date=date.today(),
                    record_type='alta',
                    record_hash=aeat_hash,
                    issuer_nif='B12345678',
                ),
            ],
            total_count=1,
        )

        with patch.object(
            reconciliation_service,
            'has_certificate',
            return_value=True,
        ), patch.object(
            reconciliation_service,
            '_get_config',
            return_value=mock_config,
        ), patch.object(
            reconciliation_service,
            '_get_aeat_client',
            return_value=mock_aeat_client,
        ), patch('verifactu.services.reconciliation_service.VerifactuRecord') as MockRecord:
            MockRecord.objects.filter.return_value.order_by.return_value.first.return_value = mock_local_record
            MockRecord.objects.filter.return_value.count.return_value = 1

            result = reconciliation_service.reconcile()

            assert result.status == ReconciliationStatus.MISMATCH_DETECTED
            assert result.local_last_hash == local_hash
            assert result.aeat_last_hash == aeat_hash
            assert result.needs_attention is True

    @pytest.mark.django_db
    def test_reconcile_empty_local_empty_aeat(
        self,
        reconciliation_service,
        mock_config,
        mock_aeat_client,
    ):
        """Test reconcile with no records on either side."""
        mock_aeat_client.query_last_records.return_value = AEATQueryResponse(
            success=True,
            code='OK',
            message='No records found',
            records=[],
            total_count=0,
        )

        with patch.object(
            reconciliation_service,
            'has_certificate',
            return_value=True,
        ), patch.object(
            reconciliation_service,
            '_get_config',
            return_value=mock_config,
        ), patch.object(
            reconciliation_service,
            '_get_aeat_client',
            return_value=mock_aeat_client,
        ), patch('verifactu.services.reconciliation_service.VerifactuRecord') as MockRecord:
            MockRecord.objects.filter.return_value.order_by.return_value.first.return_value = None
            MockRecord.objects.filter.return_value.count.return_value = 0

            result = reconciliation_service.reconcile()

            assert result.status == ReconciliationStatus.SUCCESS
            assert result.local_last_hash == ""
            assert result.aeat_last_hash == ""


class TestReconcileOnCertificateConfig:
    """Tests for reconcile_on_certificate_config function."""

    def test_returns_none_when_no_certificate(self):
        """Test returns None when no certificate configured."""
        with patch(
            'verifactu.services.reconciliation_service.ReconciliationService'
        ) as MockService:
            mock_service = Mock()
            mock_service.has_certificate.return_value = False
            MockService.return_value = mock_service

            result = reconcile_on_certificate_config()

            assert result is None

    def test_performs_reconciliation_with_certificate(self):
        """Test performs reconciliation when certificate is configured."""
        mock_result = ReconciliationResult(
            status=ReconciliationStatus.SUCCESS,
            message="Synced",
        )

        with patch(
            'verifactu.services.reconciliation_service.ReconciliationService'
        ) as MockService, patch(
            'verifactu.services.reconciliation_service.VerifactuEvent'
        ):
            mock_service = Mock()
            mock_service.has_certificate.return_value = True
            mock_service.reconcile.return_value = mock_result
            MockService.return_value = mock_service

            result = reconcile_on_certificate_config()

            assert result == mock_result
            mock_service.reconcile.assert_called_once()
            mock_service.close.assert_called_once()

    def test_logs_mismatch_event(self):
        """Test logs warning event when mismatch detected."""
        mock_result = ReconciliationResult(
            status=ReconciliationStatus.MISMATCH_DETECTED,
            message="Mismatch detected",
            discrepancies=[{'type': 'hash_mismatch'}],
        )

        with patch(
            'verifactu.services.reconciliation_service.ReconciliationService'
        ) as MockService, patch(
            'verifactu.services.reconciliation_service.VerifactuEvent'
        ) as MockEvent:
            mock_service = Mock()
            mock_service.has_certificate.return_value = True
            mock_service.reconcile.return_value = mock_result
            MockService.return_value = mock_service

            result = reconcile_on_certificate_config()

            # Should log warning event
            MockEvent.log.assert_called()
            call_args = MockEvent.log.call_args
            assert call_args.kwargs['severity'] == 'warning'


class TestGetAEATLastHash:
    """Tests for get_aeat_last_hash method."""

    def test_returns_none_without_certificate(self, reconciliation_service):
        """Test returns None when no certificate."""
        with patch.object(
            reconciliation_service,
            'has_certificate',
            return_value=False,
        ):
            result = reconciliation_service.get_aeat_last_hash()
            assert result is None

    def test_returns_hash_from_aeat(self, reconciliation_service, mock_config):
        """Test returns hash from AEAT client."""
        expected_hash = 'A' * 64

        mock_client = Mock()
        mock_client.get_last_hash.return_value = expected_hash

        with patch.object(
            reconciliation_service,
            'has_certificate',
            return_value=True,
        ), patch.object(
            reconciliation_service,
            '_get_config',
            return_value=mock_config,
        ), patch.object(
            reconciliation_service,
            '_get_aeat_client',
            return_value=mock_client,
        ):
            result = reconciliation_service.get_aeat_last_hash()

            assert result == expected_hash
            mock_client.get_last_hash.assert_called_once_with('B12345678')
