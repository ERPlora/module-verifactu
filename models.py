"""
Verifactu Models - Spanish Electronic Invoicing Compliance
Real Decreto 1007/2023 - VERI*FACTU

This module implements the data models for:
- Configuration settings
- Invoice records with hash chain
- Transmission events and audit log
- Contingency queue management
"""

from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator
from decimal import Decimal
import hashlib
import json


class VerifactuConfig(models.Model):
    """
    Singleton configuration for Verifactu module.
    Stores certificate paths, API settings, and operational parameters.
    """

    class Mode(models.TextChoices):
        VERIFACTU = 'verifactu', _('VERI*FACTU (Real-time transmission)')
        NO_VERIFACTU = 'no_verifactu', _('NO VERI*FACTU (Local storage)')

    class Environment(models.TextChoices):
        PRODUCTION = 'production', _('Production')
        TESTING = 'testing', _('Testing (Staging)')

    # General Settings
    enabled = models.BooleanField(
        _('Enabled'),
        default=False,
        help_text=_('Enable Verifactu compliance')
    )
    mode = models.CharField(
        _('Mode'),
        max_length=20,
        choices=Mode.choices,
        default=Mode.VERIFACTU,
        help_text=_('VERIFACTU mode transmits in real-time to AEAT')
    )
    environment = models.CharField(
        _('Environment'),
        max_length=20,
        choices=Environment.choices,
        default=Environment.TESTING,
        help_text=_('Use Testing for development, Production for live data')
    )

    # Software Identification (required by AEAT)
    software_name = models.CharField(
        _('Software Name'),
        max_length=100,
        default='ERPlora Hub',
        help_text=_('Name of the invoicing software')
    )
    software_version = models.CharField(
        _('Software Version'),
        max_length=20,
        default='1.0.0'
    )
    software_id = models.CharField(
        _('Software ID'),
        max_length=50,
        default='ERPLORA-001',
        help_text=_('Unique identifier for the software')
    )
    software_nif = models.CharField(
        _('Software Provider NIF'),
        max_length=15,
        blank=True,
        help_text=_('NIF of the software provider company')
    )

    # Certificate Settings
    certificate_path = models.CharField(
        _('Certificate Path'),
        max_length=500,
        blank=True,
        help_text=_('Path to PKCS#12 certificate file (.p12/.pfx)')
    )
    certificate_password = models.CharField(
        _('Certificate Password'),
        max_length=200,
        blank=True,
        help_text=_('Encrypted password for certificate')
    )
    certificate_expiry = models.DateField(
        _('Certificate Expiry'),
        null=True,
        blank=True,
        help_text=_('Expiration date of the certificate')
    )

    # Transmission Settings
    auto_transmit = models.BooleanField(
        _('Auto Transmit'),
        default=True,
        help_text=_('Automatically transmit records to AEAT')
    )
    retry_interval_minutes = models.PositiveIntegerField(
        _('Retry Interval (minutes)'),
        default=5,
        validators=[MinValueValidator(1), MaxValueValidator(60)],
        help_text=_('Minutes between retry attempts')
    )
    max_retries = models.PositiveIntegerField(
        _('Max Retries'),
        default=10,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
        help_text=_('Maximum number of retry attempts')
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Verifactu Configuration')
        verbose_name_plural = _('Verifactu Configuration')

    def __str__(self):
        return f"Verifactu Config ({self.get_mode_display()})"

    def save(self, *args, **kwargs):
        # Ensure only one config exists (singleton)
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_config(cls):
        """Get or create the singleton configuration."""
        config, _ = cls.objects.get_or_create(pk=1)
        return config

    @property
    def is_production(self):
        return self.environment == self.Environment.PRODUCTION

    @property
    def is_verifactu_mode(self):
        return self.mode == self.Mode.VERIFACTU

    @property
    def aeat_endpoint(self):
        """Return appropriate AEAT endpoint based on environment."""
        if self.is_production:
            return 'https://www1.agenciatributaria.gob.es/wlpl/TIKE-CONT/ws/'
        return 'https://prewww1.aeat.es/wlpl/TIKE-CONT/ws/'

    def days_until_certificate_expiry(self):
        """Return days until certificate expires, or None if not set."""
        if not self.certificate_expiry:
            return None
        return (self.certificate_expiry - timezone.now().date()).days


class VerifactuRecord(models.Model):
    """
    Individual Verifactu record linked to an invoice.
    Implements SHA-256 hash chain for integrity and traceability.
    """

    class RecordType(models.TextChoices):
        ALTA = 'alta', _('Registration (Alta)')
        ANULACION = 'anulacion', _('Cancellation (Anulación)')

    class InvoiceType(models.TextChoices):
        F1 = 'F1', _('F1 - Standard Invoice')
        F2 = 'F2', _('F2 - Simplified Invoice')
        F3 = 'F3', _('F3 - Invoice substituting simplified')
        R1 = 'R1', _('R1 - Rectifying (Art. 80.1-2)')
        R2 = 'R2', _('R2 - Rectifying (Art. 80.3)')
        R3 = 'R3', _('R3 - Rectifying (Art. 80.4)')
        R4 = 'R4', _('R4 - Rectifying (other)')
        R5 = 'R5', _('R5 - Rectifying simplified')

    class TransmissionStatus(models.TextChoices):
        PENDING = 'pending', _('Pending')
        TRANSMITTED = 'transmitted', _('Transmitted')
        ACCEPTED = 'accepted', _('Accepted by AEAT')
        REJECTED = 'rejected', _('Rejected by AEAT')
        ERROR = 'error', _('Transmission Error')
        RETRY = 'retry', _('Pending Retry')

    # Record Identification
    record_type = models.CharField(
        _('Record Type'),
        max_length=20,
        choices=RecordType.choices,
        default=RecordType.ALTA
    )
    sequence_number = models.PositiveIntegerField(
        _('Sequence Number'),
        help_text=_('Sequential number for hash chain ordering')
    )

    # Invoice Reference
    invoice = models.ForeignKey(
        'invoicing.Invoice',
        on_delete=models.PROTECT,
        related_name='verifactu_records',
        verbose_name=_('Invoice'),
        null=True,
        blank=True
    )

    # Issuer Data (snapshot at record creation)
    issuer_nif = models.CharField(_('Issuer NIF'), max_length=15)
    issuer_name = models.CharField(_('Issuer Name'), max_length=200)

    # Invoice Data (snapshot at record creation)
    invoice_number = models.CharField(_('Invoice Number'), max_length=60)
    invoice_date = models.DateField(_('Invoice Date'))
    invoice_type = models.CharField(
        _('Invoice Type'),
        max_length=5,
        choices=InvoiceType.choices,
        default=InvoiceType.F1
    )
    description = models.CharField(_('Description'), max_length=500, blank=True)

    # Amounts
    base_amount = models.DecimalField(
        _('Base Amount'),
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00')
    )
    tax_rate = models.DecimalField(
        _('Tax Rate'),
        max_digits=5,
        decimal_places=2,
        default=Decimal('21.00')
    )
    tax_amount = models.DecimalField(
        _('Tax Amount'),
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00')
    )
    total_amount = models.DecimalField(
        _('Total Amount'),
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00')
    )

    # Hash Chain
    previous_hash = models.CharField(
        _('Previous Hash'),
        max_length=64,
        blank=True,
        help_text=_('SHA-256 hash of previous record (empty for first record)')
    )
    record_hash = models.CharField(
        _('Record Hash'),
        max_length=64,
        help_text=_('SHA-256 hash of this record')
    )
    is_first_record = models.BooleanField(
        _('Is First Record'),
        default=False,
        help_text=_('True if this is the first record in the chain')
    )

    # Timestamp
    generation_timestamp = models.DateTimeField(
        _('Generation Timestamp'),
        help_text=_('Exact moment of record generation (with timezone)')
    )

    # Transmission Status
    status = models.CharField(
        _('Status'),
        max_length=20,
        choices=TransmissionStatus.choices,
        default=TransmissionStatus.PENDING
    )
    transmission_timestamp = models.DateTimeField(
        _('Transmission Timestamp'),
        null=True,
        blank=True
    )
    retry_count = models.PositiveIntegerField(_('Retry Count'), default=0)
    next_retry_at = models.DateTimeField(
        _('Next Retry At'),
        null=True,
        blank=True
    )

    # AEAT Response
    aeat_response_code = models.CharField(
        _('AEAT Response Code'),
        max_length=20,
        blank=True
    )
    aeat_response_message = models.TextField(
        _('AEAT Response Message'),
        blank=True
    )
    aeat_csv = models.CharField(
        _('AEAT CSV'),
        max_length=100,
        blank=True,
        help_text=_('Secure Verification Code from AEAT')
    )

    # QR Code
    qr_url = models.URLField(_('QR Verification URL'), blank=True)
    qr_generated = models.BooleanField(_('QR Generated'), default=False)

    # XML Storage
    xml_content = models.TextField(
        _('XML Content'),
        blank=True,
        help_text=_('Generated XML for this record')
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Verifactu Record')
        verbose_name_plural = _('Verifactu Records')
        ordering = ['-sequence_number']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['issuer_nif', 'invoice_number']),
            models.Index(fields=['generation_timestamp']),
            models.Index(fields=['sequence_number']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['issuer_nif', 'invoice_number', 'invoice_date', 'record_type'],
                name='unique_verifactu_record'
            )
        ]

    def __str__(self):
        return f"{self.get_record_type_display()}: {self.invoice_number}"

    def calculate_hash(self):
        """
        Calculate SHA-256 hash for this record.
        Uses the official AEAT specification for hash input fields.
        """
        timestamp_str = self.generation_timestamp.strftime('%Y-%m-%dT%H:%M:%S%z')
        # Format: +01:00 instead of +0100
        if len(timestamp_str) > 5 and timestamp_str[-3] != ':':
            timestamp_str = timestamp_str[:-2] + ':' + timestamp_str[-2:]

        if self.record_type == self.RecordType.ALTA:
            hash_input = (
                f"IDEmisorFactura={self.issuer_nif}"
                f"&NumSerieFactura={self.invoice_number}"
                f"&FechaExpedicionFactura={self.invoice_date.strftime('%d-%m-%Y')}"
                f"&TipoFactura={self.invoice_type}"
                f"&CuotaTotal={self.tax_amount:.2f}"
                f"&ImporteTotal={self.total_amount:.2f}"
                f"&Huella={self.previous_hash}"
                f"&FechaHoraHusoGenRegistro={timestamp_str}"
            )
        else:  # ANULACION
            hash_input = (
                f"IDEmisorFactura={self.issuer_nif}"
                f"&NumSerieFactura={self.invoice_number}"
                f"&FechaExpedicionFactura={self.invoice_date.strftime('%d-%m-%Y')}"
                f"&Huella={self.previous_hash}"
                f"&FechaHoraHusoGenRegistro={timestamp_str}"
            )

        return hashlib.sha256(hash_input.encode('utf-8')).hexdigest().upper()

    def generate_qr_url(self):
        """Generate the QR verification URL for AEAT."""
        base_url = "https://www2.agenciatributaria.gob.es/wlpl/TIKE-CONT/ValidarQR"
        params = (
            f"?nif={self.issuer_nif}"
            f"&numserie={self.invoice_number}"
            f"&fecha={self.invoice_date.strftime('%d-%m-%Y')}"
            f"&importe={self.total_amount:.2f}"
        )
        return base_url + params

    def save(self, *args, **kwargs):
        # Auto-set generation timestamp
        if not self.generation_timestamp:
            self.generation_timestamp = timezone.now()

        # Calculate hash if not set
        if not self.record_hash:
            self.record_hash = self.calculate_hash()

        # Generate QR URL if not set
        if not self.qr_url:
            self.qr_url = self.generate_qr_url()

        super().save(*args, **kwargs)


class VerifactuEvent(models.Model):
    """
    Audit log for Verifactu events.
    Tracks all system events, errors, and transmission attempts.
    """

    class EventType(models.TextChoices):
        RECORD_CREATED = 'record_created', _('Record Created')
        TRANSMISSION_ATTEMPT = 'transmission_attempt', _('Transmission Attempt')
        TRANSMISSION_SUCCESS = 'transmission_success', _('Transmission Success')
        TRANSMISSION_FAILURE = 'transmission_failure', _('Transmission Failure')
        RETRY_SCHEDULED = 'retry_scheduled', _('Retry Scheduled')
        CONNECTION_ERROR = 'connection_error', _('Connection Error')
        AEAT_ERROR = 'aeat_error', _('AEAT Error')
        CHAIN_VALIDATION = 'chain_validation', _('Chain Validation')
        CHAIN_ERROR = 'chain_error', _('Chain Error')
        CERTIFICATE_WARNING = 'certificate_warning', _('Certificate Warning')
        CONFIG_CHANGED = 'config_changed', _('Configuration Changed')
        CONTINGENCY_START = 'contingency_start', _('Contingency Mode Started')
        CONTINGENCY_END = 'contingency_end', _('Contingency Mode Ended')

    class Severity(models.TextChoices):
        DEBUG = 'debug', _('Debug')
        INFO = 'info', _('Info')
        WARNING = 'warning', _('Warning')
        ERROR = 'error', _('Error')
        CRITICAL = 'critical', _('Critical')

    record = models.ForeignKey(
        VerifactuRecord,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='events',
        verbose_name=_('Related Record')
    )
    event_type = models.CharField(
        _('Event Type'),
        max_length=30,
        choices=EventType.choices
    )
    severity = models.CharField(
        _('Severity'),
        max_length=10,
        choices=Severity.choices,
        default=Severity.INFO
    )
    message = models.TextField(_('Message'))
    details = models.JSONField(
        _('Details'),
        default=dict,
        blank=True,
        help_text=_('Additional event details in JSON format')
    )
    timestamp = models.DateTimeField(_('Timestamp'), auto_now_add=True)

    class Meta:
        verbose_name = _('Verifactu Event')
        verbose_name_plural = _('Verifactu Events')
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['event_type']),
            models.Index(fields=['severity']),
            models.Index(fields=['timestamp']),
        ]

    def __str__(self):
        return f"[{self.get_severity_display()}] {self.get_event_type_display()}"

    @classmethod
    def log(cls, event_type, message, severity='info', record=None, **details):
        """Convenience method to create event log entries."""
        return cls.objects.create(
            record=record,
            event_type=event_type,
            severity=severity,
            message=message,
            details=details
        )


class ContingencyQueue(models.Model):
    """
    Queue for records pending transmission during contingency mode.
    Used when AEAT is unavailable or connection fails.
    """

    class Priority(models.IntegerChoices):
        HIGH = 1, _('High')
        NORMAL = 2, _('Normal')
        LOW = 3, _('Low')

    record = models.OneToOneField(
        VerifactuRecord,
        on_delete=models.CASCADE,
        related_name='contingency_entry',
        verbose_name=_('Record')
    )
    priority = models.IntegerField(
        _('Priority'),
        choices=Priority.choices,
        default=Priority.NORMAL
    )
    queued_at = models.DateTimeField(_('Queued At'), auto_now_add=True)
    attempts = models.PositiveIntegerField(_('Attempts'), default=0)
    last_attempt_at = models.DateTimeField(
        _('Last Attempt At'),
        null=True,
        blank=True
    )
    last_error = models.TextField(_('Last Error'), blank=True)
    next_attempt_at = models.DateTimeField(
        _('Next Attempt At'),
        null=True,
        blank=True
    )

    class Meta:
        verbose_name = _('Contingency Queue Entry')
        verbose_name_plural = _('Contingency Queue')
        ordering = ['priority', 'queued_at']

    def __str__(self):
        return f"Queue: {self.record.invoice_number} (Attempt #{self.attempts})"

    def schedule_retry(self, interval_minutes=5):
        """Schedule next retry attempt."""
        self.attempts += 1
        self.last_attempt_at = timezone.now()
        # Exponential backoff: 5, 10, 20, 40, 60 (max) minutes
        backoff = min(interval_minutes * (2 ** (self.attempts - 1)), 60)
        self.next_attempt_at = timezone.now() + timezone.timedelta(minutes=backoff)
        self.save()

    @classmethod
    def get_ready_for_retry(cls):
        """Get queue entries ready for retry."""
        return cls.objects.filter(
            next_attempt_at__lte=timezone.now()
        ).select_related('record').order_by('priority', 'queued_at')

    @classmethod
    def get_pending_count(cls):
        """Get count of pending queue entries."""
        return cls.objects.count()
