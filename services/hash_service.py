"""
Hash Service for Verifactu
Implements SHA-256 hash chain as per AEAT specifications.

Reference: Veri-Factu_especificaciones_huella_hash_registros.pdf v0.1.2
"""

import hashlib
from datetime import datetime
from decimal import Decimal
from typing import Optional
from django.utils import timezone


class HashServiceError(Exception):
    """Base exception for hash service errors."""
    pass


class ChainCorruptionError(HashServiceError):
    """Raised when hash chain integrity is compromised."""
    pass


class HashService:
    """
    Service for generating and validating SHA-256 hash chains.

    The hash chain ensures:
    - Integrity: Any modification is detectable
    - Traceability: Complete audit trail
    - Immutability: Records cannot be altered without detection
    """

    ALGORITHM = 'SHA-256'

    @staticmethod
    def format_timestamp(dt: datetime) -> str:
        """
        Format datetime for hash input.
        Format: 2025-01-15T17:22:14+01:00

        Args:
            dt: Datetime object (must be timezone aware)

        Returns:
            ISO format string with proper timezone offset
        """
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt)

        # Get ISO format and fix timezone format (Python uses +0100, AEAT wants +01:00)
        iso_str = dt.strftime('%Y-%m-%dT%H:%M:%S%z')
        if len(iso_str) > 5 and iso_str[-3] != ':':
            iso_str = iso_str[:-2] + ':' + iso_str[-2:]

        return iso_str

    @staticmethod
    def format_date(date) -> str:
        """
        Format date for hash input.
        Format: DD-MM-YYYY

        Args:
            date: Date object

        Returns:
            Date string in DD-MM-YYYY format
        """
        return date.strftime('%d-%m-%Y')

    @staticmethod
    def format_amount(amount: Decimal) -> str:
        """
        Format decimal amount for hash input.
        Format: 2 decimal places, no thousands separator

        Args:
            amount: Decimal amount

        Returns:
            Formatted amount string
        """
        return f"{amount:.2f}"

    @classmethod
    def calculate_alta_hash(
        cls,
        issuer_nif: str,
        invoice_number: str,
        invoice_date,
        invoice_type: str,
        tax_amount: Decimal,
        total_amount: Decimal,
        previous_hash: str,
        generation_timestamp: datetime
    ) -> str:
        """
        Calculate hash for an Alta (registration) record.

        Args:
            issuer_nif: NIF of the invoice issuer
            invoice_number: Invoice number/series
            invoice_date: Invoice date
            invoice_type: Type code (F1, F2, R1, etc.)
            tax_amount: Total tax amount (CuotaTotal)
            total_amount: Total invoice amount (ImporteTotal)
            previous_hash: Hash of the previous record (empty string if first)
            generation_timestamp: Record generation timestamp

        Returns:
            SHA-256 hash in uppercase hexadecimal
        """
        hash_input = (
            f"IDEmisorFactura={issuer_nif}"
            f"&NumSerieFactura={invoice_number}"
            f"&FechaExpedicionFactura={cls.format_date(invoice_date)}"
            f"&TipoFactura={invoice_type}"
            f"&CuotaTotal={cls.format_amount(tax_amount)}"
            f"&ImporteTotal={cls.format_amount(total_amount)}"
            f"&Huella={previous_hash}"
            f"&FechaHoraHusoGenRegistro={cls.format_timestamp(generation_timestamp)}"
        )

        return hashlib.sha256(hash_input.encode('utf-8')).hexdigest().upper()

    @classmethod
    def calculate_anulacion_hash(
        cls,
        issuer_nif: str,
        invoice_number: str,
        invoice_date,
        previous_hash: str,
        generation_timestamp: datetime
    ) -> str:
        """
        Calculate hash for an Anulación (cancellation) record.

        Args:
            issuer_nif: NIF of the invoice issuer
            invoice_number: Original invoice number
            invoice_date: Original invoice date
            previous_hash: Hash of the previous record
            generation_timestamp: Record generation timestamp

        Returns:
            SHA-256 hash in uppercase hexadecimal
        """
        hash_input = (
            f"IDEmisorFactura={issuer_nif}"
            f"&NumSerieFactura={invoice_number}"
            f"&FechaExpedicionFactura={cls.format_date(invoice_date)}"
            f"&Huella={previous_hash}"
            f"&FechaHoraHusoGenRegistro={cls.format_timestamp(generation_timestamp)}"
        )

        return hashlib.sha256(hash_input.encode('utf-8')).hexdigest().upper()

    @classmethod
    def validate_hash(cls, record) -> bool:
        """
        Validate that a record's hash matches its content.

        Args:
            record: VerifactuRecord instance

        Returns:
            True if hash is valid, False otherwise
        """
        if record.record_type == 'alta':
            expected_hash = cls.calculate_alta_hash(
                issuer_nif=record.issuer_nif,
                invoice_number=record.invoice_number,
                invoice_date=record.invoice_date,
                invoice_type=record.invoice_type,
                tax_amount=record.tax_amount,
                total_amount=record.total_amount,
                previous_hash=record.previous_hash,
                generation_timestamp=record.generation_timestamp
            )
        else:
            expected_hash = cls.calculate_anulacion_hash(
                issuer_nif=record.issuer_nif,
                invoice_number=record.invoice_number,
                invoice_date=record.invoice_date,
                previous_hash=record.previous_hash,
                generation_timestamp=record.generation_timestamp
            )

        return record.record_hash == expected_hash

    @classmethod
    def validate_chain(cls, records: list) -> tuple[bool, Optional[int]]:
        """
        Validate the integrity of a hash chain.

        Args:
            records: List of VerifactuRecord instances, ordered by sequence_number

        Returns:
            Tuple of (is_valid, first_invalid_index)
            If valid, returns (True, None)
            If invalid, returns (False, index of first invalid record)
        """
        for i, record in enumerate(records):
            # Validate individual record hash
            if not cls.validate_hash(record):
                return False, i

            # Validate chain linkage
            if i == 0:
                # First record should have empty previous_hash or is_first_record=True
                if record.previous_hash and not record.is_first_record:
                    return False, i
            else:
                # Subsequent records should link to previous
                expected_previous = records[i - 1].record_hash
                if record.previous_hash != expected_previous:
                    return False, i

        return True, None

    @classmethod
    def get_last_hash(cls, issuer_nif: str, check_aeat_recovery: bool = True) -> str:
        """
        Get the hash of the last record for an issuer.

        If local records exist, returns the last local hash.
        If no local records but AEAT has records (recovery scenario),
        attempts to get the last hash from AEAT.

        Args:
            issuer_nif: NIF of the issuer
            check_aeat_recovery: If True, check AEAT when local is empty

        Returns:
            Hash of the last record, or empty string if no records exist
        """
        from verifactu.models import VerifactuRecord, VerifactuConfig

        last_record = VerifactuRecord.objects.filter(
            issuer_nif=issuer_nif
        ).order_by('-sequence_number').first()

        if last_record:
            return last_record.record_hash

        # No local records - check if we should recover from AEAT
        if not check_aeat_recovery:
            return ""

        # Check if certificate is configured and we can query AEAT
        config = VerifactuConfig.get_config()
        if not config.certificate_path or not config.certificate_password:
            return ""

        # Attempt to get last hash from AEAT (recovery scenario)
        try:
            from verifactu.services.reconciliation_service import ReconciliationService

            service = ReconciliationService()
            aeat_hash = service.get_aeat_last_hash(issuer_nif)

            if aeat_hash:
                from verifactu.models import VerifactuEvent
                VerifactuEvent.log(
                    event_type=VerifactuEvent.EventType.CHAIN_VALIDATION,
                    message=f"Usando hash de AEAT para continuar cadena: {aeat_hash[:16]}...",
                    severity='info',
                    issuer_nif=issuer_nif,
                    aeat_hash=aeat_hash,
                )
                return aeat_hash

        except Exception as e:
            import logging
            logger = logging.getLogger('verifactu.hash_service')
            logger.warning(f"Could not get AEAT hash for recovery: {e}")

        return ""

    @classmethod
    def get_next_sequence_number(cls, issuer_nif: str) -> int:
        """
        Get the next sequence number for an issuer.

        Args:
            issuer_nif: NIF of the issuer

        Returns:
            Next sequence number (1 if no records exist)
        """
        from verifactu.models import VerifactuRecord

        last_record = VerifactuRecord.objects.filter(
            issuer_nif=issuer_nif
        ).order_by('-sequence_number').first()

        return (last_record.sequence_number + 1) if last_record else 1

    @classmethod
    def create_record_from_invoice(cls, invoice, record_type='alta') -> 'VerifactuRecord':
        """
        Create a new VerifactuRecord from an Invoice.

        Args:
            invoice: Invoice model instance
            record_type: 'alta' for registration, 'anulacion' for cancellation

        Returns:
            VerifactuRecord instance (not saved)
        """
        from verifactu.models import VerifactuRecord, VerifactuConfig

        config = VerifactuConfig.get_config()

        # Get issuer info from config or invoice
        issuer_nif = config.software_nif or invoice.series.prefix  # TODO: Get from StoreConfig
        issuer_name = config.software_name

        # Get chain info
        previous_hash = cls.get_last_hash(issuer_nif)
        sequence_number = cls.get_next_sequence_number(issuer_nif)
        is_first = sequence_number == 1

        # Create record
        record = VerifactuRecord(
            record_type=record_type,
            sequence_number=sequence_number,
            invoice=invoice,
            issuer_nif=issuer_nif,
            issuer_name=issuer_name,
            invoice_number=invoice.number,
            invoice_date=invoice.issue_date,
            invoice_type='F1' if invoice.invoice_type == 'standard' else 'F2',
            description=f"Invoice {invoice.number}",
            base_amount=invoice.subtotal,
            tax_rate=invoice.tax_rate,
            tax_amount=invoice.tax_amount,
            total_amount=invoice.total,
            previous_hash=previous_hash,
            is_first_record=is_first,
            generation_timestamp=timezone.now()
        )

        # Calculate hash
        if record_type == 'alta':
            record.record_hash = cls.calculate_alta_hash(
                issuer_nif=record.issuer_nif,
                invoice_number=record.invoice_number,
                invoice_date=record.invoice_date,
                invoice_type=record.invoice_type,
                tax_amount=record.tax_amount,
                total_amount=record.total_amount,
                previous_hash=record.previous_hash,
                generation_timestamp=record.generation_timestamp
            )
        else:
            record.record_hash = cls.calculate_anulacion_hash(
                issuer_nif=record.issuer_nif,
                invoice_number=record.invoice_number,
                invoice_date=record.invoice_date,
                previous_hash=record.previous_hash,
                generation_timestamp=record.generation_timestamp
            )

        return record

    @classmethod
    def validate_hash_format(cls, hash_value: str) -> bool:
        """
        Validate that a hash has the correct format.

        Args:
            hash_value: Hash string to validate

        Returns:
            True if valid format, False otherwise
        """
        if not hash_value or len(hash_value) != 64:
            return False

        # Must be uppercase hex
        return all(c in '0123456789ABCDEF' for c in hash_value)

    @classmethod
    def verify_chain_linkage(
        cls,
        current_hash: str,
        expected_previous: str,
        actual_previous: str,
    ) -> bool:
        """
        Verify that chain linkage is correct.

        Args:
            current_hash: The current record's hash
            expected_previous: What the previous hash should be
            actual_previous: What the previous hash actually is

        Returns:
            True if linkage is valid, False otherwise
        """
        return expected_previous == actual_previous
