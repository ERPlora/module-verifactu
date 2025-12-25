"""
Contingency Manager for Verifactu
Handles offline mode, retries, and failure recovery.

Implements contingency plans for:
1. Network connectivity failures
2. AEAT service unavailability
3. Hash chain corruption
4. Certificate expiration
5. Database failures
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
from enum import Enum
from dataclasses import dataclass
from django.utils import timezone
from django.db import transaction

logger = logging.getLogger('verifactu.contingency')


class ContingencyMode(Enum):
    """Contingency operation modes."""
    NORMAL = 'normal'           # Online, real-time submission
    OFFLINE = 'offline'         # No connectivity, queue records
    DEGRADED = 'degraded'       # Partial connectivity, delayed submission
    RECOVERY = 'recovery'       # Recovering from failure


class FailureType(Enum):
    """Types of failures that can occur."""
    NETWORK = 'network'
    AEAT_UNAVAILABLE = 'aeat_unavailable'
    CERTIFICATE = 'certificate'
    HASH_CHAIN = 'hash_chain'
    DATABASE = 'database'
    VALIDATION = 'validation'
    UNKNOWN = 'unknown'


@dataclass
class ContingencyStatus:
    """Current contingency status."""
    mode: ContingencyMode
    failure_type: Optional[FailureType]
    message: str
    queue_size: int
    last_successful_submission: Optional[datetime]
    next_retry: Optional[datetime]
    can_create_records: bool

    @property
    def mode_value(self) -> str:
        """Get mode value as string for templates."""
        return self.mode.value

    @property
    def failure_type_value(self) -> Optional[str]:
        """Get failure type value as string for templates."""
        return self.failure_type.value if self.failure_type else None


class ContingencyError(Exception):
    """Base exception for contingency errors."""
    pass


class ContingencyManager:
    """
    Manages contingency operations for Verifactu.

    Responsibilities:
    - Monitor system health
    - Queue records when offline
    - Retry failed submissions
    - Recover from failures
    - Alert on critical issues
    """

    # Retry configuration
    RETRY_INTERVALS = [60, 300, 900, 3600, 7200]  # seconds: 1m, 5m, 15m, 1h, 2h
    MAX_QUEUE_AGE_HOURS = 48  # Maximum hours before escalation
    MAX_QUEUE_SIZE = 1000  # Maximum queued records before warning

    # Health check intervals
    HEALTH_CHECK_INTERVAL = 60  # seconds

    def __init__(self):
        """Initialize contingency manager."""
        self._mode = ContingencyMode.NORMAL
        self._failure_type = None
        self._failure_count = 0
        self._last_health_check = None
        self._last_successful_submission = None

    @property
    def mode(self) -> ContingencyMode:
        """Get current contingency mode."""
        return self._mode

    @property
    def is_online(self) -> bool:
        """Check if system is in online mode."""
        return self._mode == ContingencyMode.NORMAL

    def get_status(self) -> ContingencyStatus:
        """
        Get current contingency status.

        Returns:
            ContingencyStatus with full system state
        """
        from verifactu.models import ContingencyQueue

        queue_count = ContingencyQueue.objects.filter(
            status__in=['pending', 'retrying']
        ).count()

        return ContingencyStatus(
            mode=self._mode,
            failure_type=self._failure_type,
            message=self._get_status_message(),
            queue_size=queue_count,
            last_successful_submission=self._last_successful_submission,
            next_retry=self._calculate_next_retry(),
            can_create_records=self._can_create_records(),
        )

    def _get_status_message(self) -> str:
        """Get human-readable status message."""
        messages = {
            ContingencyMode.NORMAL: "Sistema operativo - Modo online",
            ContingencyMode.OFFLINE: "Sin conexión - Registros en cola",
            ContingencyMode.DEGRADED: "Conexión intermitente - Reintentando",
            ContingencyMode.RECOVERY: "Recuperando registros pendientes",
        }
        base = messages.get(self._mode, "Estado desconocido")

        if self._failure_type:
            failure_messages = {
                FailureType.NETWORK: " (Error de red)",
                FailureType.AEAT_UNAVAILABLE: " (AEAT no disponible)",
                FailureType.CERTIFICATE: " (Error de certificado)",
                FailureType.HASH_CHAIN: " (Error en cadena hash)",
                FailureType.DATABASE: " (Error de base de datos)",
            }
            base += failure_messages.get(self._failure_type, "")

        return base

    def _can_create_records(self) -> bool:
        """Check if new records can be created."""
        # Can always create records, they'll be queued if offline
        # Only block on hash chain corruption
        return self._failure_type != FailureType.HASH_CHAIN

    def _calculate_next_retry(self) -> Optional[datetime]:
        """Calculate next retry time based on failure count."""
        if self._mode == ContingencyMode.NORMAL:
            return None

        interval_index = min(self._failure_count, len(self.RETRY_INTERVALS) - 1)
        interval = self.RETRY_INTERVALS[interval_index]
        return timezone.now() + timedelta(seconds=interval)

    def record_success(self, record_id: int):
        """
        Record a successful submission.

        Args:
            record_id: ID of successfully submitted record
        """
        self._last_successful_submission = timezone.now()
        self._failure_count = 0

        if self._mode != ContingencyMode.NORMAL:
            logger.info("Returning to normal mode after successful submission")
            self._mode = ContingencyMode.NORMAL
            self._failure_type = None

    def record_failure(
        self,
        failure_type: FailureType,
        error_message: str,
        record_id: Optional[int] = None,
    ):
        """
        Record a failure and adjust mode accordingly.

        Args:
            failure_type: Type of failure
            error_message: Error description
            record_id: ID of failed record (if applicable)
        """
        from verifactu.models import VerifactuEvent

        self._failure_count += 1
        self._failure_type = failure_type

        # Log the event
        VerifactuEvent.objects.create(
            event_type='error',
            description=f"Failure: {failure_type.value} - {error_message}",
            record_id=record_id,
        )

        logger.warning(
            f"Verifactu failure recorded: {failure_type.value} - {error_message}"
        )

        # Determine new mode
        if failure_type in [FailureType.NETWORK, FailureType.AEAT_UNAVAILABLE]:
            if self._failure_count >= 3:
                self._mode = ContingencyMode.OFFLINE
            else:
                self._mode = ContingencyMode.DEGRADED
        elif failure_type == FailureType.HASH_CHAIN:
            self._mode = ContingencyMode.RECOVERY
            logger.critical("Hash chain corruption detected - manual intervention required")
        elif failure_type == FailureType.CERTIFICATE:
            self._mode = ContingencyMode.OFFLINE
            logger.critical("Certificate error - check certificate validity")

    def queue_record(
        self,
        record,
        reason: str,
        priority: int = 0,
    ):
        """
        Add a record to the contingency queue.

        Args:
            record: VerifactuRecord to queue
            reason: Reason for queueing
            priority: Queue priority (0 = normal)
        """
        from verifactu.models import ContingencyQueue

        ContingencyQueue.objects.create(
            record=record,
            reason=reason,
            priority=priority,
            retry_count=0,
        )

        logger.info(f"Record {record.id} queued for later submission: {reason}")

    def get_pending_records(self, limit: int = 100) -> List:
        """
        Get records pending submission.

        Args:
            limit: Maximum records to return

        Returns:
            List of ContingencyQueue entries
        """
        from verifactu.models import ContingencyQueue

        return list(ContingencyQueue.objects.filter(
            status__in=['pending', 'retrying'],
            next_retry__lte=timezone.now(),
        ).select_related('record').order_by('priority', 'created_at')[:limit])

    def process_queue(self) -> Tuple[int, int]:
        """
        Process pending records in the queue.

        Returns:
            Tuple of (successful_count, failed_count)
        """
        from verifactu.models import ContingencyQueue, VerifactuEvent
        from .aeat_client import AEATClient, AEATClientError
        from .xml_service import XMLService

        if self._mode == ContingencyMode.OFFLINE:
            # Don't process if definitely offline
            return 0, 0

        pending = self.get_pending_records()
        if not pending:
            return 0, 0

        logger.info(f"Processing {len(pending)} queued records")

        successful = 0
        failed = 0

        # Get AEAT client
        try:
            from verifactu.models import VerifactuConfig
            config = VerifactuConfig.get_config()
            if not config or not config.certificate_path:
                logger.error("No valid configuration for AEAT client")
                return 0, len(pending)

            client = AEATClient(
                certificate_path=config.certificate_path,
                certificate_password=config.certificate_password,
                environment=config.environment,
            )
        except Exception as e:
            logger.error(f"Failed to create AEAT client: {e}")
            return 0, len(pending)

        try:
            for queue_entry in pending:
                try:
                    record = queue_entry.record

                    # Generate XML
                    xml_content = XMLService.generate_record_xml(record, config)

                    # Submit to AEAT
                    response = client.submit_record(xml_content, record.record_type)

                    if response.success:
                        # Update record
                        record.status = 'transmitted'
                        record.aeat_csv = response.csv
                        record.transmission_timestamp = response.timestamp
                        record.save()

                        # Remove from queue
                        queue_entry.status = 'completed'
                        queue_entry.save()

                        self.record_success(record.id)
                        successful += 1

                        VerifactuEvent.objects.create(
                            event_type='transmission',
                            description=f"Queued record submitted successfully",
                            record=record,
                        )

                    else:
                        # Update retry count
                        queue_entry.retry_count += 1
                        queue_entry.last_error = response.message
                        queue_entry.status = 'retrying'
                        queue_entry.next_retry = self._calculate_next_retry()
                        queue_entry.save()

                        self.record_failure(
                            FailureType.AEAT_UNAVAILABLE,
                            response.message,
                            record.id,
                        )
                        failed += 1

                except AEATClientError as e:
                    queue_entry.retry_count += 1
                    queue_entry.last_error = str(e)
                    queue_entry.status = 'retrying'
                    queue_entry.next_retry = self._calculate_next_retry()
                    queue_entry.save()

                    self.record_failure(FailureType.NETWORK, str(e))
                    failed += 1

                except Exception as e:
                    logger.error(f"Unexpected error processing queue entry: {e}")
                    queue_entry.retry_count += 1
                    queue_entry.last_error = str(e)
                    queue_entry.status = 'failed' if queue_entry.retry_count > 5 else 'retrying'
                    queue_entry.save()
                    failed += 1

        finally:
            client.close()

        logger.info(f"Queue processing complete: {successful} successful, {failed} failed")
        return successful, failed

    def check_health(self) -> Tuple[bool, str]:
        """
        Perform health check of Verifactu system.

        Returns:
            Tuple of (is_healthy, message)
        """
        from verifactu.models import VerifactuConfig, ContingencyQueue

        issues = []

        # Check configuration
        try:
            config = VerifactuConfig.get_config()
            if not config:
                issues.append("No Verifactu configuration found")
            elif not config.certificate_path:
                issues.append("No certificate configured")
            elif config.is_certificate_expiring():
                issues.append("Certificate expiring soon")
        except Exception as e:
            issues.append(f"Configuration error: {e}")

        # Check queue size
        queue_count = ContingencyQueue.objects.filter(
            status__in=['pending', 'retrying']
        ).count()
        if queue_count > self.MAX_QUEUE_SIZE:
            issues.append(f"Queue size critical: {queue_count} records")
        elif queue_count > self.MAX_QUEUE_SIZE // 2:
            issues.append(f"Queue size warning: {queue_count} records")

        # Check for old queued records
        old_threshold = timezone.now() - timedelta(hours=self.MAX_QUEUE_AGE_HOURS)
        old_count = ContingencyQueue.objects.filter(
            status__in=['pending', 'retrying'],
            created_at__lt=old_threshold,
        ).count()
        if old_count > 0:
            issues.append(f"{old_count} records queued for more than {self.MAX_QUEUE_AGE_HOURS}h")

        self._last_health_check = timezone.now()

        if issues:
            return False, "; ".join(issues)
        return True, "System healthy"

    def verify_hash_chain(self) -> Tuple[bool, Optional[str]]:
        """
        Verify integrity of hash chain.

        Returns:
            Tuple of (is_valid, error_message)
        """
        from verifactu.models import VerifactuRecord
        from .hash_service import HashService

        logger.info("Starting hash chain verification")

        records = VerifactuRecord.objects.filter(
            status__in=['transmitted', 'accepted']
        ).order_by('generation_timestamp')

        previous_hash = None
        first_record = True

        for record in records:
            # Calculate expected hash
            if record.record_type == 'alta':
                expected_hash = HashService.calculate_alta_hash(
                    issuer_nif=record.issuer_nif,
                    invoice_number=record.invoice_number,
                    invoice_date=record.invoice_date,
                    invoice_type=record.invoice_type,
                    tax_amount=record.tax_amount,
                    total_amount=record.total_amount,
                    previous_hash=previous_hash or '',
                    generation_timestamp=record.generation_timestamp,
                )
            else:
                expected_hash = HashService.calculate_anulacion_hash(
                    issuer_nif=record.issuer_nif,
                    invoice_number=record.invoice_number,
                    invoice_date=record.invoice_date,
                    previous_hash=previous_hash or '',
                    generation_timestamp=record.generation_timestamp,
                )

            # Verify
            if record.record_hash != expected_hash:
                error_msg = f"Hash mismatch at record {record.id} ({record.invoice_number})"
                logger.error(error_msg)
                self.record_failure(FailureType.HASH_CHAIN, error_msg, record.id)
                return False, error_msg

            # Check chain linkage
            if not first_record and record.previous_hash != previous_hash:
                error_msg = f"Chain linkage error at record {record.id}"
                logger.error(error_msg)
                self.record_failure(FailureType.HASH_CHAIN, error_msg, record.id)
                return False, error_msg

            previous_hash = record.record_hash
            first_record = False

        logger.info("Hash chain verification passed")
        return True, None

    def escalate_alert(self, alert_type: str, message: str):
        """
        Escalate a critical alert.

        Args:
            alert_type: Type of alert
            message: Alert message
        """
        from verifactu.models import VerifactuEvent

        logger.critical(f"VERIFACTU ALERT [{alert_type}]: {message}")

        VerifactuEvent.objects.create(
            event_type='alert',
            description=f"[{alert_type}] {message}",
        )

        # TODO: Implement actual alerting (email, SMS, webhook)
        # This would integrate with the Hub's notification system


# Singleton instance
_contingency_manager = None


def get_contingency_manager() -> ContingencyManager:
    """Get the singleton contingency manager instance."""
    global _contingency_manager
    if _contingency_manager is None:
        _contingency_manager = ContingencyManager()
    return _contingency_manager
