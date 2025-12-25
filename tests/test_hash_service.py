"""
Unit tests for Verifactu Hash Service.

Tests SHA-256 hash generation according to AEAT specifications.
"""

import pytest
from datetime import date, datetime
from decimal import Decimal
from django.utils import timezone

from verifactu.services.hash_service import HashService


class TestHashService:
    """Unit tests for HashService."""

    def test_calculate_alta_hash_basic(self):
        """Test basic alta hash calculation."""
        result = HashService.calculate_alta_hash(
            issuer_nif='B12345678',
            invoice_number='F2024-001',
            invoice_date=date(2024, 12, 25),
            invoice_type='F1',
            tax_amount=Decimal('21.00'),
            total_amount=Decimal('121.00'),
            previous_hash='',
            generation_timestamp=datetime(2024, 12, 25, 10, 30, 0, tzinfo=timezone.utc),
        )

        # Hash should be uppercase hex string
        assert result is not None
        assert len(result) == 64  # SHA-256 produces 64 hex characters
        assert result == result.upper()
        assert all(c in '0123456789ABCDEF' for c in result)

    def test_calculate_alta_hash_deterministic(self):
        """Test that same inputs produce same hash."""
        params = {
            'issuer_nif': 'B12345678',
            'invoice_number': 'F2024-001',
            'invoice_date': date(2024, 12, 25),
            'invoice_type': 'F1',
            'tax_amount': Decimal('21.00'),
            'total_amount': Decimal('121.00'),
            'previous_hash': '',
            'generation_timestamp': datetime(2024, 12, 25, 10, 30, 0, tzinfo=timezone.utc),
        }

        hash1 = HashService.calculate_alta_hash(**params)
        hash2 = HashService.calculate_alta_hash(**params)

        assert hash1 == hash2

    def test_calculate_alta_hash_different_inputs_different_hash(self):
        """Test that different inputs produce different hashes."""
        base_params = {
            'issuer_nif': 'B12345678',
            'invoice_number': 'F2024-001',
            'invoice_date': date(2024, 12, 25),
            'invoice_type': 'F1',
            'tax_amount': Decimal('21.00'),
            'total_amount': Decimal('121.00'),
            'previous_hash': '',
            'generation_timestamp': datetime(2024, 12, 25, 10, 30, 0, tzinfo=timezone.utc),
        }

        hash1 = HashService.calculate_alta_hash(**base_params)

        # Change invoice number
        modified_params = base_params.copy()
        modified_params['invoice_number'] = 'F2024-002'
        hash2 = HashService.calculate_alta_hash(**modified_params)

        assert hash1 != hash2

    def test_calculate_alta_hash_with_previous_hash(self):
        """Test alta hash with previous hash (chain linkage)."""
        previous_hash = 'A' * 64  # Mock previous hash

        result = HashService.calculate_alta_hash(
            issuer_nif='B12345678',
            invoice_number='F2024-002',
            invoice_date=date(2024, 12, 25),
            invoice_type='F1',
            tax_amount=Decimal('21.00'),
            total_amount=Decimal('121.00'),
            previous_hash=previous_hash,
            generation_timestamp=datetime(2024, 12, 25, 10, 30, 0, tzinfo=timezone.utc),
        )

        assert result is not None
        assert len(result) == 64

    def test_calculate_anulacion_hash_basic(self):
        """Test basic anulación hash calculation."""
        result = HashService.calculate_anulacion_hash(
            issuer_nif='B12345678',
            invoice_number='F2024-001',
            invoice_date=date(2024, 12, 25),
            previous_hash='A' * 64,
            generation_timestamp=datetime(2024, 12, 25, 10, 30, 0, tzinfo=timezone.utc),
        )

        assert result is not None
        assert len(result) == 64
        assert result == result.upper()

    def test_calculate_anulacion_hash_deterministic(self):
        """Test that same inputs produce same anulación hash."""
        params = {
            'issuer_nif': 'B12345678',
            'invoice_number': 'F2024-001',
            'invoice_date': date(2024, 12, 25),
            'previous_hash': 'A' * 64,
            'generation_timestamp': datetime(2024, 12, 25, 10, 30, 0, tzinfo=timezone.utc),
        }

        hash1 = HashService.calculate_anulacion_hash(**params)
        hash2 = HashService.calculate_anulacion_hash(**params)

        assert hash1 == hash2

    def test_alta_and_anulacion_hashes_differ(self):
        """Test that alta and anulación produce different hashes for same invoice."""
        common_params = {
            'issuer_nif': 'B12345678',
            'invoice_number': 'F2024-001',
            'invoice_date': date(2024, 12, 25),
            'previous_hash': 'A' * 64,
            'generation_timestamp': datetime(2024, 12, 25, 10, 30, 0, tzinfo=timezone.utc),
        }

        alta_hash = HashService.calculate_alta_hash(
            **common_params,
            invoice_type='F1',
            tax_amount=Decimal('21.00'),
            total_amount=Decimal('121.00'),
        )

        anulacion_hash = HashService.calculate_anulacion_hash(**common_params)

        assert alta_hash != anulacion_hash

    def test_format_timestamp_naive_datetime(self):
        """Test timestamp formatting with naive datetime."""
        naive_dt = datetime(2024, 12, 25, 10, 30, 0)
        result = HashService.format_timestamp(naive_dt)

        # Should include timezone offset
        assert '+' in result or '-' in result
        assert 'T' in result

    def test_format_timestamp_aware_datetime(self):
        """Test timestamp formatting with aware datetime."""
        aware_dt = datetime(2024, 12, 25, 10, 30, 0, tzinfo=timezone.utc)
        result = HashService.format_timestamp(aware_dt)

        assert result == '2024-12-25T10:30:00+00:00'

    def test_format_amount_basic(self):
        """Test amount formatting."""
        assert HashService.format_amount(Decimal('100')) == '100.00'
        assert HashService.format_amount(Decimal('100.5')) == '100.50'
        assert HashService.format_amount(Decimal('100.555')) == '100.56'  # Rounded
        assert HashService.format_amount(Decimal('0')) == '0.00'

    def test_format_date(self):
        """Test date formatting (DD-MM-YYYY)."""
        result = HashService.format_date(date(2024, 12, 25))
        assert result == '25-12-2024'

    def test_hash_chain_integrity(self):
        """Test hash chain integrity - each hash depends on previous."""
        ts = datetime(2024, 12, 25, 10, 0, 0, tzinfo=timezone.utc)

        # First record (no previous hash)
        hash1 = HashService.calculate_alta_hash(
            issuer_nif='B12345678',
            invoice_number='F2024-001',
            invoice_date=date(2024, 12, 25),
            invoice_type='F1',
            tax_amount=Decimal('21.00'),
            total_amount=Decimal('121.00'),
            previous_hash='',
            generation_timestamp=ts,
        )

        # Second record (links to first)
        hash2 = HashService.calculate_alta_hash(
            issuer_nif='B12345678',
            invoice_number='F2024-002',
            invoice_date=date(2024, 12, 25),
            invoice_type='F1',
            tax_amount=Decimal('42.00'),
            total_amount=Decimal('242.00'),
            previous_hash=hash1,
            generation_timestamp=datetime(2024, 12, 25, 10, 1, 0, tzinfo=timezone.utc),
        )

        # Third record (links to second)
        hash3 = HashService.calculate_alta_hash(
            issuer_nif='B12345678',
            invoice_number='F2024-003',
            invoice_date=date(2024, 12, 25),
            invoice_type='F1',
            tax_amount=Decimal('63.00'),
            total_amount=Decimal('363.00'),
            previous_hash=hash2,
            generation_timestamp=datetime(2024, 12, 25, 10, 2, 0, tzinfo=timezone.utc),
        )

        # All hashes should be unique
        assert hash1 != hash2 != hash3
        assert len({hash1, hash2, hash3}) == 3

    def test_nif_formats(self):
        """Test hash calculation with different NIF formats."""
        params = {
            'invoice_number': 'F2024-001',
            'invoice_date': date(2024, 12, 25),
            'invoice_type': 'F1',
            'tax_amount': Decimal('21.00'),
            'total_amount': Decimal('121.00'),
            'previous_hash': '',
            'generation_timestamp': datetime(2024, 12, 25, 10, 30, 0, tzinfo=timezone.utc),
        }

        # Different NIF types
        nifs = ['B12345678', 'A98765432', '12345678Z', 'X1234567L']

        hashes = []
        for nif in nifs:
            h = HashService.calculate_alta_hash(issuer_nif=nif, **params)
            hashes.append(h)
            assert len(h) == 64

        # All should be different
        assert len(set(hashes)) == len(nifs)

    def test_special_characters_in_invoice_number(self):
        """Test hash calculation with special characters in invoice number."""
        result = HashService.calculate_alta_hash(
            issuer_nif='B12345678',
            invoice_number='F2024/001-A',
            invoice_date=date(2024, 12, 25),
            invoice_type='F1',
            tax_amount=Decimal('21.00'),
            total_amount=Decimal('121.00'),
            previous_hash='',
            generation_timestamp=datetime(2024, 12, 25, 10, 30, 0, tzinfo=timezone.utc),
        )

        assert result is not None
        assert len(result) == 64

    def test_large_amounts(self):
        """Test hash calculation with large amounts."""
        result = HashService.calculate_alta_hash(
            issuer_nif='B12345678',
            invoice_number='F2024-001',
            invoice_date=date(2024, 12, 25),
            invoice_type='F1',
            tax_amount=Decimal('210000.00'),
            total_amount=Decimal('1210000.00'),
            previous_hash='',
            generation_timestamp=datetime(2024, 12, 25, 10, 30, 0, tzinfo=timezone.utc),
        )

        assert result is not None
        assert len(result) == 64

    def test_zero_amounts(self):
        """Test hash calculation with zero tax (e.g., exempt invoices)."""
        result = HashService.calculate_alta_hash(
            issuer_nif='B12345678',
            invoice_number='F2024-001',
            invoice_date=date(2024, 12, 25),
            invoice_type='F1',
            tax_amount=Decimal('0.00'),
            total_amount=Decimal('100.00'),
            previous_hash='',
            generation_timestamp=datetime(2024, 12, 25, 10, 30, 0, tzinfo=timezone.utc),
        )

        assert result is not None
        assert len(result) == 64


class TestHashValidation:
    """Tests for hash validation and verification."""

    def test_validate_hash_format_valid(self):
        """Test validation of valid hash format."""
        valid_hash = 'A' * 64
        assert HashService.validate_hash_format(valid_hash) is True

    def test_validate_hash_format_invalid_length(self):
        """Test validation rejects invalid length."""
        assert HashService.validate_hash_format('A' * 63) is False
        assert HashService.validate_hash_format('A' * 65) is False
        assert HashService.validate_hash_format('') is False

    def test_validate_hash_format_invalid_characters(self):
        """Test validation rejects invalid characters."""
        assert HashService.validate_hash_format('G' * 64) is False  # G not in hex
        assert HashService.validate_hash_format('a' * 64) is False  # lowercase
        assert HashService.validate_hash_format(' ' + 'A' * 63) is False  # space

    def test_verify_chain_linkage_valid(self):
        """Test chain verification with valid linkage."""
        ts = datetime(2024, 12, 25, 10, 0, 0, tzinfo=timezone.utc)

        hash1 = HashService.calculate_alta_hash(
            issuer_nif='B12345678',
            invoice_number='F2024-001',
            invoice_date=date(2024, 12, 25),
            invoice_type='F1',
            tax_amount=Decimal('21.00'),
            total_amount=Decimal('121.00'),
            previous_hash='',
            generation_timestamp=ts,
        )

        # Verify linkage
        is_valid = HashService.verify_chain_linkage(
            current_hash=hash1,
            expected_previous='',
            actual_previous='',
        )
        assert is_valid is True

    def test_verify_chain_linkage_invalid(self):
        """Test chain verification with broken linkage."""
        is_valid = HashService.verify_chain_linkage(
            current_hash='A' * 64,
            expected_previous='B' * 64,
            actual_previous='C' * 64,  # Mismatch!
        )
        assert is_valid is False
