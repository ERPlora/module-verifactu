"""
Reconciliation Service for Verifactu

Synchronizes local hash chain with AEAT records when:
1. Certificate is configured for the first time
2. Database is restored from backup
3. Manual reconciliation is triggered

This ensures chain integrity after data recovery scenarios.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Tuple
from enum import Enum

from django.utils import timezone

logger = logging.getLogger('verifactu.reconciliation')


class ReconciliationStatus(Enum):
    """Status of reconciliation process."""
    NOT_STARTED = 'not_started'
    IN_PROGRESS = 'in_progress'
    SUCCESS = 'success'
    FAILED = 'failed'
    MISMATCH_DETECTED = 'mismatch_detected'
    NO_CERTIFICATE = 'no_certificate'
    AEAT_UNAVAILABLE = 'aeat_unavailable'
    CHAIN_RECOVERED = 'chain_recovered'
    MANUAL_INTERVENTION_REQUIRED = 'manual_intervention_required'


class ConflictType(Enum):
    """Types of conflicts between local and AEAT."""
    NONE = 'none'
    LOCAL_BEHIND = 'local_behind'  # Local has fewer records (backup restore)
    LOCAL_AHEAD = 'local_ahead'    # Local has pending records (contingency)
    HASH_MISMATCH = 'hash_mismatch'  # Same records but different hashes (corruption)
    MISSING_LOCAL = 'missing_local'  # Records in AEAT not in local
    UNKNOWN = 'unknown'


@dataclass
class ReconciliationResult:
    """Result of a reconciliation check."""
    status: ReconciliationStatus
    message: str
    conflict_type: ConflictType = ConflictType.NONE
    local_last_hash: Optional[str] = None
    aeat_last_hash: Optional[str] = None
    local_record_count: int = 0
    aeat_record_count: int = 0
    discrepancies: List[dict] = None
    recommended_action: Optional[str] = None
    can_auto_resolve: bool = False
    timestamp: Optional[datetime] = None

    def __post_init__(self):
        if self.discrepancies is None:
            self.discrepancies = []
        if self.timestamp is None:
            self.timestamp = datetime.now()

    @property
    def is_synced(self) -> bool:
        """Check if local and AEAT are synchronized."""
        return self.status in [
            ReconciliationStatus.SUCCESS,
            ReconciliationStatus.CHAIN_RECOVERED,
        ]

    @property
    def needs_attention(self) -> bool:
        """Check if reconciliation needs user attention."""
        return self.status in [
            ReconciliationStatus.MISMATCH_DETECTED,
            ReconciliationStatus.FAILED,
            ReconciliationStatus.MANUAL_INTERVENTION_REQUIRED,
        ]

    @property
    def needs_manual_intervention(self) -> bool:
        """Check if manual intervention is required."""
        return self.status == ReconciliationStatus.MANUAL_INTERVENTION_REQUIRED


class ReconciliationService:
    """
    Service for reconciling local Verifactu records with AEAT.

    Use Cases:
    ----------
    1. Certificate Configuration:
       When a certificate is configured, automatically check if local
       records match what AEAT has. This catches backup/restore issues.

    2. Manual Reconciliation:
       User can trigger reconciliation to verify chain integrity.

    3. Startup Check:
       Optionally verify chain on application startup.

    Example:
    --------
    ```python
    from verifactu.services.reconciliation_service import ReconciliationService

    service = ReconciliationService()
    result = service.reconcile()

    if result.needs_attention:
        print(f"Reconciliation issue: {result.message}")
        for discrepancy in result.discrepancies:
            print(f"  - {discrepancy}")
    ```
    """

    def __init__(self):
        """Initialize reconciliation service."""
        self._aeat_client = None

    def _get_config(self):
        """Get Verifactu configuration."""
        from verifactu.models import VerifactuConfig
        return VerifactuConfig.get_config()

    def _get_aeat_client(self):
        """Get or create AEAT client."""
        if self._aeat_client is not None:
            return self._aeat_client

        from verifactu.services.aeat_client import AEATClient, AEATEnvironment

        config = self._get_config()

        if not config.certificate_path or not config.certificate_password:
            return None

        environment = (
            AEATEnvironment.PRODUCTION
            if config.is_production
            else AEATEnvironment.TESTING
        )

        self._aeat_client = AEATClient(
            certificate_path=config.certificate_path,
            certificate_password=config.certificate_password,
            environment=environment,
        )

        return self._aeat_client

    def has_certificate(self) -> bool:
        """Check if certificate is configured."""
        config = self._get_config()
        return bool(config.certificate_path and config.certificate_password)

    def reconcile(self, issuer_nif: str = None) -> ReconciliationResult:
        """
        Perform reconciliation between local records and AEAT.

        This compares:
        1. Last record hash in local database
        2. Last record hash in AEAT

        If they match, the chain is synchronized.
        If they don't match, there may be missing records or corruption.

        Args:
            issuer_nif: NIF to reconcile. If None, uses config software_nif.

        Returns:
            ReconciliationResult with status and details.
        """
        logger.info("Starting reconciliation check")

        # Check certificate
        if not self.has_certificate():
            logger.warning("No certificate configured - cannot reconcile")
            return ReconciliationResult(
                status=ReconciliationStatus.NO_CERTIFICATE,
                message="No se puede reconciliar sin certificado configurado",
            )

        config = self._get_config()

        # Get issuer NIF
        if issuer_nif is None:
            issuer_nif = config.software_nif

        if not issuer_nif:
            return ReconciliationResult(
                status=ReconciliationStatus.FAILED,
                message="No hay NIF de emisor configurado",
            )

        # Get local state
        from verifactu.models import VerifactuRecord
        from verifactu.services.hash_service import HashService

        local_last_record = VerifactuRecord.objects.filter(
            issuer_nif=issuer_nif
        ).order_by('-sequence_number').first()

        local_last_hash = local_last_record.record_hash if local_last_record else ""
        local_count = VerifactuRecord.objects.filter(issuer_nif=issuer_nif).count()

        # Query AEAT
        try:
            client = self._get_aeat_client()
            if client is None:
                return ReconciliationResult(
                    status=ReconciliationStatus.NO_CERTIFICATE,
                    message="No se puede crear cliente AEAT - certificado inválido",
                )

            aeat_response = client.query_last_records(issuer_nif, limit=10)

            if not aeat_response.success:
                logger.error(f"AEAT query failed: {aeat_response.message}")
                return ReconciliationResult(
                    status=ReconciliationStatus.AEAT_UNAVAILABLE,
                    message=f"Error consultando AEAT: {aeat_response.message}",
                    local_last_hash=local_last_hash,
                    local_record_count=local_count,
                )

        except Exception as e:
            logger.exception(f"AEAT connection error: {e}")
            return ReconciliationResult(
                status=ReconciliationStatus.AEAT_UNAVAILABLE,
                message=f"Error de conexión con AEAT: {str(e)}",
                local_last_hash=local_last_hash,
                local_record_count=local_count,
            )

        # Compare records
        aeat_last_hash = (
            aeat_response.records[0].record_hash
            if aeat_response.records
            else ""
        )
        aeat_count = aeat_response.total_count

        # Check if synchronized
        if local_last_hash == aeat_last_hash:
            logger.info("Reconciliation successful - chains are synchronized")
            return ReconciliationResult(
                status=ReconciliationStatus.SUCCESS,
                message="Cadena sincronizada con AEAT",
                local_last_hash=local_last_hash,
                aeat_last_hash=aeat_last_hash,
                local_record_count=local_count,
                aeat_record_count=aeat_count,
            )

        # Chains don't match - find discrepancies
        logger.warning("Chain mismatch detected")
        discrepancies = self._find_discrepancies(
            issuer_nif,
            aeat_response.records,
        )

        return ReconciliationResult(
            status=ReconciliationStatus.MISMATCH_DETECTED,
            message="Discrepancia detectada entre registros locales y AEAT",
            local_last_hash=local_last_hash,
            aeat_last_hash=aeat_last_hash,
            local_record_count=local_count,
            aeat_record_count=aeat_count,
            discrepancies=discrepancies,
        )

    def _find_discrepancies(
        self,
        issuer_nif: str,
        aeat_records: list,
    ) -> List[dict]:
        """
        Find specific discrepancies between local and AEAT records.

        Args:
            issuer_nif: NIF of the issuer
            aeat_records: Records returned from AEAT query

        Returns:
            List of discrepancy dictionaries
        """
        from verifactu.models import VerifactuRecord

        discrepancies = []

        for aeat_record in aeat_records:
            # Find matching local record
            local_record = VerifactuRecord.objects.filter(
                issuer_nif=issuer_nif,
                invoice_number=aeat_record.invoice_number,
                invoice_date=aeat_record.invoice_date,
            ).first()

            if local_record is None:
                discrepancies.append({
                    'type': 'missing_local',
                    'invoice_number': aeat_record.invoice_number,
                    'invoice_date': str(aeat_record.invoice_date),
                    'aeat_hash': aeat_record.record_hash,
                    'message': f"Registro {aeat_record.invoice_number} existe en AEAT pero no localmente",
                })
            elif local_record.record_hash != aeat_record.record_hash:
                discrepancies.append({
                    'type': 'hash_mismatch',
                    'invoice_number': aeat_record.invoice_number,
                    'invoice_date': str(aeat_record.invoice_date),
                    'local_hash': local_record.record_hash,
                    'aeat_hash': aeat_record.record_hash,
                    'message': f"Hash de {aeat_record.invoice_number} no coincide",
                })

        # Check for local records not in AEAT
        aeat_invoice_numbers = {r.invoice_number for r in aeat_records}
        local_records = VerifactuRecord.objects.filter(
            issuer_nif=issuer_nif,
            status='accepted',  # Only check accepted records
        ).order_by('-sequence_number')[:len(aeat_records)]

        for local_record in local_records:
            if local_record.invoice_number not in aeat_invoice_numbers:
                discrepancies.append({
                    'type': 'missing_aeat',
                    'invoice_number': local_record.invoice_number,
                    'invoice_date': str(local_record.invoice_date),
                    'local_hash': local_record.record_hash,
                    'message': f"Registro {local_record.invoice_number} existe localmente pero no en AEAT",
                })

        return discrepancies

    def sync_from_aeat(self, issuer_nif: str = None) -> ReconciliationResult:
        """
        Synchronize local chain from AEAT.

        USE WITH CAUTION: This updates local records to match AEAT.
        Only use after a backup restore when AEAT is the source of truth.

        This will:
        1. Query AEAT for all records
        2. Update local previous_hash values to match AEAT chain
        3. NOT create missing records (that must be done manually)

        Args:
            issuer_nif: NIF to sync. If None, uses config software_nif.

        Returns:
            ReconciliationResult with sync status.
        """
        logger.info("Starting sync from AEAT")

        # First reconcile to see current state
        result = self.reconcile(issuer_nif)

        if result.status == ReconciliationStatus.SUCCESS:
            return result  # Already synced

        if result.status in [
            ReconciliationStatus.NO_CERTIFICATE,
            ReconciliationStatus.AEAT_UNAVAILABLE,
        ]:
            return result  # Can't sync

        # Get AEAT's last hash to use for next record
        config = self._get_config()

        if issuer_nif is None:
            issuer_nif = config.software_nif

        try:
            client = self._get_aeat_client()
            aeat_response = client.query_last_records(issuer_nif, limit=1)

            if aeat_response.success and aeat_response.records:
                aeat_last_hash = aeat_response.records[0].record_hash

                # Store the AEAT hash for next record creation
                # This allows continuing the chain correctly after restore
                from verifactu.models import VerifactuEvent
                VerifactuEvent.log(
                    event_type=VerifactuEvent.EventType.CHAIN_VALIDATION,
                    message=f"Sincronizado hash de AEAT para continuar cadena",
                    severity='info',
                    aeat_last_hash=aeat_last_hash,
                    issuer_nif=issuer_nif,
                )

                logger.info(f"AEAT last hash stored: {aeat_last_hash[:16]}...")

                return ReconciliationResult(
                    status=ReconciliationStatus.SUCCESS,
                    message="Hash de AEAT obtenido para continuar cadena",
                    aeat_last_hash=aeat_last_hash,
                    aeat_record_count=aeat_response.total_count,
                )

        except Exception as e:
            logger.exception(f"Sync error: {e}")
            return ReconciliationResult(
                status=ReconciliationStatus.FAILED,
                message=f"Error sincronizando desde AEAT: {str(e)}",
            )

        return ReconciliationResult(
            status=ReconciliationStatus.FAILED,
            message="No se pudo obtener información de AEAT",
        )

    def get_aeat_last_hash(self, issuer_nif: str = None) -> Optional[str]:
        """
        Get the last hash from AEAT.

        Convenience method for chain recovery.

        Args:
            issuer_nif: NIF of the issuer

        Returns:
            Last hash from AEAT or None if unavailable
        """
        if not self.has_certificate():
            return None

        config = self._get_config()
        if issuer_nif is None:
            issuer_nif = config.software_nif

        if not issuer_nif:
            return None

        try:
            client = self._get_aeat_client()
            if client:
                return client.get_last_hash(issuer_nif)
        except Exception as e:
            logger.error(f"Error getting AEAT last hash: {e}")

        return None

    def diagnose_conflict(self, issuer_nif: str = None) -> ReconciliationResult:
        """
        Diagnose the type of conflict and recommend action.

        This is a more detailed analysis than reconcile() that determines:
        1. What type of conflict exists
        2. Whether it can be automatically resolved
        3. What action to take

        Returns:
            ReconciliationResult with conflict_type and recommended_action
        """
        # First do basic reconciliation
        result = self.reconcile(issuer_nif)

        if result.status == ReconciliationStatus.SUCCESS:
            result.conflict_type = ConflictType.NONE
            return result

        if result.status in [
            ReconciliationStatus.NO_CERTIFICATE,
            ReconciliationStatus.AEAT_UNAVAILABLE,
        ]:
            return result

        # Analyze the conflict type
        local_count = result.local_record_count
        aeat_count = result.aeat_record_count

        if local_count == 0 and aeat_count > 0:
            # Local is empty but AEAT has records - backup restore scenario
            result.conflict_type = ConflictType.LOCAL_BEHIND
            result.can_auto_resolve = True
            result.recommended_action = (
                "Se detectaron registros en AEAT que no existen localmente. "
                "Esto ocurre tras restaurar un backup. "
                "Se puede continuar usando el último hash de AEAT para la próxima factura."
            )

        elif local_count > 0 and aeat_count == 0:
            # Local has records but AEAT is empty - pending transmission
            result.conflict_type = ConflictType.LOCAL_AHEAD
            result.can_auto_resolve = True
            result.recommended_action = (
                "Hay registros locales pendientes de enviar a AEAT. "
                "Estos se enviarán automáticamente cuando haya conexión."
            )

        elif result.local_last_hash != result.aeat_last_hash:
            # Both have records but hashes don't match
            # Check if it's a simple "local behind" or actual corruption
            if self._is_local_behind(issuer_nif, result.aeat_last_hash):
                result.conflict_type = ConflictType.LOCAL_BEHIND
                result.can_auto_resolve = True
                result.recommended_action = (
                    "La base de datos local está desactualizada respecto a AEAT. "
                    "Se puede continuar usando el último hash de AEAT."
                )
            else:
                result.conflict_type = ConflictType.HASH_MISMATCH
                result.can_auto_resolve = False
                result.status = ReconciliationStatus.MANUAL_INTERVENTION_REQUIRED
                result.recommended_action = (
                    "ATENCIÓN: Los hashes no coinciden y no es un simple desfase. "
                    "Esto puede indicar corrupción de datos o modificación manual. "
                    "Se requiere revisión manual por un profesional. "
                    "NO cree nuevas facturas hasta resolver este problema."
                )

        return result

    def _is_local_behind(self, issuer_nif: str, aeat_last_hash: str) -> bool:
        """
        Check if local is simply behind AEAT (not corrupted).

        This happens when:
        - We restored a backup from before some invoices were sent
        - The AEAT hash is in our chain history (but not the last one)

        Returns:
            True if local is behind but chain is intact
        """
        from verifactu.models import VerifactuRecord

        # If AEAT's last hash exists somewhere in our chain, we're just behind
        exists = VerifactuRecord.objects.filter(
            issuer_nif=issuer_nif,
            record_hash=aeat_last_hash,
        ).exists()

        return exists

    def resolve_conflict(self, issuer_nif: str = None) -> ReconciliationResult:
        """
        Attempt to automatically resolve a conflict.

        Only resolves conflicts that can be auto-resolved:
        - LOCAL_BEHIND: Update chain pointer to AEAT's last hash
        - LOCAL_AHEAD: Trigger contingency queue processing

        For HASH_MISMATCH, returns MANUAL_INTERVENTION_REQUIRED.

        Returns:
            ReconciliationResult with resolution status
        """
        logger.info("Attempting to resolve conflict")

        # First diagnose
        diagnosis = self.diagnose_conflict(issuer_nif)

        if diagnosis.conflict_type == ConflictType.NONE:
            return diagnosis

        if not diagnosis.can_auto_resolve:
            logger.warning("Conflict cannot be auto-resolved")
            return diagnosis

        config = self._get_config()
        if issuer_nif is None:
            issuer_nif = config.software_nif

        # Resolve based on conflict type
        if diagnosis.conflict_type == ConflictType.LOCAL_BEHIND:
            return self._resolve_local_behind(issuer_nif, diagnosis)

        elif diagnosis.conflict_type == ConflictType.LOCAL_AHEAD:
            return self._resolve_local_ahead(issuer_nif, diagnosis)

        return diagnosis

    def _resolve_local_behind(
        self,
        issuer_nif: str,
        diagnosis: ReconciliationResult,
    ) -> ReconciliationResult:
        """
        Resolve LOCAL_BEHIND conflict.

        Strategy:
        - Get AEAT's last hash
        - Store it as the chain continuation point
        - Next invoice will use this hash as previous_hash

        This is safe because AEAT is the source of truth.
        """
        from verifactu.models import VerifactuEvent

        aeat_last_hash = diagnosis.aeat_last_hash

        if not aeat_last_hash:
            return ReconciliationResult(
                status=ReconciliationStatus.FAILED,
                message="No se pudo obtener el último hash de AEAT",
                conflict_type=ConflictType.LOCAL_BEHIND,
            )

        # Log the recovery
        VerifactuEvent.log(
            event_type=VerifactuEvent.EventType.CHAIN_VALIDATION,
            message=f"Cadena recuperada desde AEAT. Último hash: {aeat_last_hash[:16]}...",
            severity='info',
            issuer_nif=issuer_nif,
            aeat_hash=aeat_last_hash,
            action='chain_recovery',
        )

        logger.info(f"Chain recovered from AEAT for {issuer_nif}")

        return ReconciliationResult(
            status=ReconciliationStatus.CHAIN_RECOVERED,
            message="Cadena recuperada. La próxima factura usará el hash de AEAT.",
            conflict_type=ConflictType.LOCAL_BEHIND,
            aeat_last_hash=aeat_last_hash,
            can_auto_resolve=True,
            recommended_action="Cadena sincronizada. Puede continuar creando facturas.",
        )

    def _resolve_local_ahead(
        self,
        issuer_nif: str,
        diagnosis: ReconciliationResult,
    ) -> ReconciliationResult:
        """
        Resolve LOCAL_AHEAD conflict.

        Strategy:
        - Check contingency queue for pending records
        - Trigger transmission of pending records

        This happens when invoices were created but not transmitted.
        """
        from verifactu.models import ContingencyQueue, VerifactuEvent

        # Check pending queue
        pending_count = ContingencyQueue.get_pending_count()

        if pending_count == 0:
            # No pending items - check for untransmitted records
            from verifactu.models import VerifactuRecord
            untransmitted = VerifactuRecord.objects.filter(
                issuer_nif=issuer_nif,
                status__in=['pending', 'retry'],
            ).count()

            if untransmitted == 0:
                return ReconciliationResult(
                    status=ReconciliationStatus.SUCCESS,
                    message="No hay registros pendientes de transmisión",
                    conflict_type=ConflictType.NONE,
                )

        VerifactuEvent.log(
            event_type=VerifactuEvent.EventType.TRANSMISSION_ATTEMPT,
            message=f"Iniciando transmisión de {pending_count} registros pendientes",
            severity='info',
            issuer_nif=issuer_nif,
            pending_count=pending_count,
        )

        # Note: Actual transmission should be done by a Celery task
        # Here we just mark that it needs to happen

        return ReconciliationResult(
            status=ReconciliationStatus.MISMATCH_DETECTED,
            message=f"Hay {pending_count} registros pendientes de enviar a AEAT",
            conflict_type=ConflictType.LOCAL_AHEAD,
            local_record_count=diagnosis.local_record_count,
            can_auto_resolve=True,
            recommended_action=(
                "Los registros pendientes se enviarán automáticamente. "
                "Verifique la conexión a internet y el estado del certificado."
            ),
        )

    def close(self):
        """Close AEAT client connection."""
        if self._aeat_client:
            self._aeat_client.close()
            self._aeat_client = None


def reconcile_on_certificate_config():
    """
    Perform reconciliation when certificate is configured.

    Called from VerifactuConfig save signal when certificate is set.

    Returns:
        ReconciliationResult or None if no certificate
    """
    service = ReconciliationService()

    if not service.has_certificate():
        return None

    try:
        result = service.reconcile()

        # Log the result
        from verifactu.models import VerifactuEvent

        if result.status == ReconciliationStatus.SUCCESS:
            VerifactuEvent.log(
                event_type=VerifactuEvent.EventType.CHAIN_VALIDATION,
                message="Reconciliación exitosa tras configurar certificado",
                severity='info',
                local_hash=result.local_last_hash,
                aeat_hash=result.aeat_last_hash,
            )
        elif result.needs_attention:
            VerifactuEvent.log(
                event_type=VerifactuEvent.EventType.CHAIN_ERROR,
                message=f"Discrepancia detectada: {result.message}",
                severity='warning',
                discrepancies=result.discrepancies,
            )

        return result

    except Exception as e:
        logger.exception(f"Reconciliation error: {e}")
        from verifactu.models import VerifactuEvent
        VerifactuEvent.log(
            event_type=VerifactuEvent.EventType.CHAIN_ERROR,
            message=f"Error en reconciliación: {str(e)}",
            severity='error',
        )
        return None

    finally:
        service.close()
