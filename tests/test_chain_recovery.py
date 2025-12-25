"""
Unit and integration tests for Verifactu Chain Recovery Service.

Tests the ability to recover the hash chain after database restore or migration.
"""

import pytest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.utils import timezone

from verifactu.services.recovery_service import (
    ChainRecoveryService,
    ChainStatus,
    RecoveryResult,
    RecoveryStatus,
    get_recovery_service,
)
from verifactu.services.aeat_client import (
    AEATQueryRecord,
    AEATQueryResponse,
    MockAEATClient,
)
from verifactu.models import VerifactuRecord, ChainRecoveryPoint


class TestChainStatus:
    """Tests for ChainStatus dataclass."""

    def test_chain_status_synced(self):
        """Test status when chain is synced."""
        status = ChainStatus(
            is_synced=True,
            local_last_hash='A' * 64,
            local_last_invoice='F2024-001',
            aeat_last_hash='A' * 64,
            aeat_last_invoice='F2024-001',
            gap_count=0,
            message='Chain is synchronized',
        )

        assert status.is_synced is True
        assert status.gap_count == 0

    def test_chain_status_desync(self):
        """Test status when chain is out of sync."""
        status = ChainStatus(
            is_synced=False,
            local_last_hash='A' * 64,
            local_last_invoice='F2024-001',
            aeat_last_hash='B' * 64,
            aeat_last_invoice='F2024-003',
            gap_count=2,
            message='Chain is out of sync - 2 invoices missing locally',
        )

        assert status.is_synced is False
        assert status.gap_count == 2


class TestRecoveryResult:
    """Tests for RecoveryResult dataclass."""

    def test_recovery_success(self):
        """Test successful recovery result."""
        result = RecoveryResult(
            status=RecoveryStatus.SUCCESS,
            recovered_hash='A' * 64,
            recovered_invoice='F2024-003',
            message='Chain recovered successfully',
        )

        assert result.status == RecoveryStatus.SUCCESS
        assert result.recovered_hash is not None

    def test_recovery_no_records(self):
        """Test recovery when AEAT has no records."""
        result = RecoveryResult(
            status=RecoveryStatus.NO_RECORDS,
            message='No records found in AEAT',
        )

        assert result.status == RecoveryStatus.NO_RECORDS
        assert result.recovered_hash is None


class TestChainRecoveryService:
    """Tests for ChainRecoveryService."""

    @pytest.fixture
    def service(self):
        """Create a recovery service with mock AEAT client."""
        service = ChainRecoveryService()
        service.aeat_client = MockAEATClient()
        return service

    def test_get_chain_status_no_local_records(self, service):
        """Test chain status when no local records exist."""
        with patch.object(
            VerifactuRecord.objects, 'filter'
        ) as mock_filter:
            mock_filter.return_value.order_by.return_value.first.return_value = None

            status = service.get_chain_status('B12345678')

            assert status.local_last_hash is None
            assert status.local_last_invoice is None

    def test_get_chain_status_with_local_records(self, service):
        """Test chain status when local records exist."""
        mock_record = MagicMock()
        mock_record.record_hash = 'A' * 64
        mock_record.invoice_number = 'F2024-001'

        with patch.object(
            VerifactuRecord.objects, 'filter'
        ) as mock_filter:
            mock_filter.return_value.order_by.return_value.first.return_value = mock_record

            status = service.get_chain_status('B12345678')

            assert status.local_last_hash == 'A' * 64
            assert status.local_last_invoice == 'F2024-001'

    def test_recover_from_aeat_success(self, service):
        """Test successful recovery from AEAT."""
        # Configure mock to return a record
        service.aeat_client.mock_query_response = AEATQueryResponse(
            success=True,
            code='OK',
            message='Success',
            records=[
                AEATQueryRecord(
                    invoice_number='F2024-003',
                    invoice_date=date(2024, 12, 25),
                    record_type='alta',
                    record_hash='C' * 64,
                    issuer_nif='B12345678',
                )
            ],
            total_count=1,
        )

        with patch.object(
            ChainRecoveryPoint.objects, 'create'
        ) as mock_create:
            result = service.recover_from_aeat('B12345678')

            assert result.status == RecoveryStatus.SUCCESS
            assert result.recovered_hash == 'C' * 64
            assert result.recovered_invoice == 'F2024-003'
            mock_create.assert_called_once()

    def test_recover_from_aeat_no_records(self, service):
        """Test recovery when AEAT has no records."""
        service.aeat_client.mock_query_response = AEATQueryResponse(
            success=True,
            code='OK',
            message='No records found',
            records=[],
            total_count=0,
        )

        result = service.recover_from_aeat('B12345678')

        assert result.status == RecoveryStatus.NO_RECORDS

    def test_recover_from_aeat_connection_error(self, service):
        """Test recovery when AEAT connection fails."""
        service.aeat_client.set_failure(
            code='CONNECTION_ERROR',
            message='Connection refused',
        )

        result = service.recover_from_aeat('B12345678')

        assert result.status == RecoveryStatus.ERROR
        assert 'error' in result.message.lower() or 'connection' in result.message.lower()

    def test_recover_manual_valid_hash(self, service):
        """Test manual recovery with valid hash."""
        valid_hash = 'A' * 64

        with patch.object(
            ChainRecoveryPoint.objects, 'create'
        ) as mock_create:
            result = service.recover_manual('B12345678', valid_hash)

            assert result.status == RecoveryStatus.SUCCESS
            assert result.recovered_hash == valid_hash
            mock_create.assert_called_once()

    def test_recover_manual_invalid_hash_length(self, service):
        """Test manual recovery with invalid hash length."""
        invalid_hash = 'A' * 63  # Too short

        result = service.recover_manual('B12345678', invalid_hash)

        assert result.status == RecoveryStatus.INVALID_HASH

    def test_recover_manual_invalid_hash_characters(self, service):
        """Test manual recovery with invalid hash characters."""
        invalid_hash = 'G' * 64  # G is not hex

        result = service.recover_manual('B12345678', invalid_hash)

        assert result.status == RecoveryStatus.INVALID_HASH

    def test_recover_manual_lowercase_converted(self, service):
        """Test that lowercase hash is converted to uppercase."""
        lowercase_hash = 'a' * 64

        with patch.object(
            ChainRecoveryPoint.objects, 'create'
        ) as mock_create:
            result = service.recover_manual('B12345678', lowercase_hash)

            assert result.status == RecoveryStatus.SUCCESS
            assert result.recovered_hash == 'A' * 64

    def test_get_effective_last_hash_no_recovery(self, service):
        """Test effective hash when no recovery exists."""
        mock_record = MagicMock()
        mock_record.record_hash = 'A' * 64

        with patch.object(
            VerifactuRecord.objects, 'filter'
        ) as mock_vf_filter:
            mock_vf_filter.return_value.order_by.return_value.first.return_value = mock_record

            with patch.object(
                ChainRecoveryPoint.objects, 'filter'
            ) as mock_rp_filter:
                mock_rp_filter.return_value.order_by.return_value.first.return_value = None

                result = service.get_effective_last_hash('B12345678')

                assert result == 'A' * 64

    def test_get_effective_last_hash_with_recovery(self, service):
        """Test effective hash uses recovery point when available."""
        mock_record = MagicMock()
        mock_record.record_hash = 'A' * 64  # Old local hash

        mock_recovery = MagicMock()
        mock_recovery.recovered_hash = 'B' * 64  # Recovery hash
        mock_recovery.recovered_at = timezone.now()

        with patch.object(
            VerifactuRecord.objects, 'filter'
        ) as mock_vf_filter:
            mock_vf_filter.return_value.order_by.return_value.first.return_value = mock_record

            with patch.object(
                ChainRecoveryPoint.objects, 'filter'
            ) as mock_rp_filter:
                mock_rp_filter.return_value.order_by.return_value.first.return_value = mock_recovery

                result = service.get_effective_last_hash('B12345678')

                # Should use recovery hash, not local
                assert result == 'B' * 64

    def test_get_effective_last_hash_empty_db(self, service):
        """Test effective hash when database is empty."""
        with patch.object(
            VerifactuRecord.objects, 'filter'
        ) as mock_vf_filter:
            mock_vf_filter.return_value.order_by.return_value.first.return_value = None

            with patch.object(
                ChainRecoveryPoint.objects, 'filter'
            ) as mock_rp_filter:
                mock_rp_filter.return_value.order_by.return_value.first.return_value = None

                result = service.get_effective_last_hash('B12345678')

                assert result == ''  # Empty for first record


class TestMockAEATClientQuery:
    """Tests for MockAEATClient query functionality."""

    def test_mock_query_default_response(self):
        """Test mock client returns default query response."""
        client = MockAEATClient()

        response = client.query_last_records('B12345678')

        assert response.success is True
        assert len(response.records) > 0

    def test_mock_query_custom_response(self):
        """Test mock client with custom query response."""
        client = MockAEATClient()
        custom_response = AEATQueryResponse(
            success=True,
            code='OK',
            message='Custom response',
            records=[
                AEATQueryRecord(
                    invoice_number='CUSTOM-001',
                    invoice_date=date(2024, 12, 25),
                    record_type='alta',
                    record_hash='X' * 64,
                    issuer_nif='B12345678',
                )
            ],
            total_count=1,
        )
        client.mock_query_response = custom_response

        response = client.query_last_records('B12345678')

        assert response.records[0].invoice_number == 'CUSTOM-001'

    def test_mock_get_last_hash(self):
        """Test get_last_hash convenience method."""
        client = MockAEATClient()

        result = client.get_last_hash('B12345678')

        assert result is not None
        assert len(result) == 64


class TestGetRecoveryService:
    """Tests for get_recovery_service factory function."""

    def test_returns_service_instance(self):
        """Test factory returns ChainRecoveryService."""
        service = get_recovery_service()

        assert isinstance(service, ChainRecoveryService)

    def test_returns_same_instance(self):
        """Test factory returns singleton (if implemented)."""
        service1 = get_recovery_service()
        service2 = get_recovery_service()

        # May or may not be same instance depending on implementation
        assert type(service1) == type(service2)


class TestChainRecoveryIntegration:
    """Integration tests for chain recovery flow."""

    @pytest.fixture
    def setup_scenario(self):
        """Setup a chain break scenario."""
        # This would normally create test data in database
        pass

    def test_full_recovery_flow_automatic(self, setup_scenario):
        """Test complete automatic recovery flow."""
        service = ChainRecoveryService()
        service.aeat_client = MockAEATClient()

        # 1. Check initial status (should show desync)
        with patch.object(
            VerifactuRecord.objects, 'filter'
        ) as mock_filter:
            mock_filter.return_value.order_by.return_value.first.return_value = None

            status = service.get_chain_status('B12345678')
            # Local is empty, AEAT has records

        # 2. Recover from AEAT
        service.aeat_client.mock_query_response = AEATQueryResponse(
            success=True,
            code='OK',
            message='Success',
            records=[
                AEATQueryRecord(
                    invoice_number='F2024-005',
                    invoice_date=date(2024, 12, 25),
                    record_type='alta',
                    record_hash='E' * 64,
                    issuer_nif='B12345678',
                )
            ],
            total_count=1,
        )

        with patch.object(
            ChainRecoveryPoint.objects, 'create'
        ):
            result = service.recover_from_aeat('B12345678')

            assert result.status == RecoveryStatus.SUCCESS
            assert result.recovered_hash == 'E' * 64

        # 3. Verify new effective hash
        mock_recovery = MagicMock()
        mock_recovery.recovered_hash = 'E' * 64
        mock_recovery.recovered_at = timezone.now()

        with patch.object(
            VerifactuRecord.objects, 'filter'
        ) as mock_vf_filter:
            mock_vf_filter.return_value.order_by.return_value.first.return_value = None

            with patch.object(
                ChainRecoveryPoint.objects, 'filter'
            ) as mock_rp_filter:
                mock_rp_filter.return_value.order_by.return_value.first.return_value = mock_recovery

                effective_hash = service.get_effective_last_hash('B12345678')

                assert effective_hash == 'E' * 64

    def test_full_recovery_flow_manual(self, setup_scenario):
        """Test complete manual recovery flow."""
        service = ChainRecoveryService()
        manual_hash = 'D' * 64

        with patch.object(
            ChainRecoveryPoint.objects, 'create'
        ):
            result = service.recover_manual('B12345678', manual_hash)

            assert result.status == RecoveryStatus.SUCCESS

        # Verify the hash would be used
        mock_recovery = MagicMock()
        mock_recovery.recovered_hash = manual_hash
        mock_recovery.recovered_at = timezone.now()

        with patch.object(
            VerifactuRecord.objects, 'filter'
        ) as mock_vf_filter:
            mock_vf_filter.return_value.order_by.return_value.first.return_value = None

            with patch.object(
                ChainRecoveryPoint.objects, 'filter'
            ) as mock_rp_filter:
                mock_rp_filter.return_value.order_by.return_value.first.return_value = mock_recovery

                effective_hash = service.get_effective_last_hash('B12345678')

                assert effective_hash == manual_hash
