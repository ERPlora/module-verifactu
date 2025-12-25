"""
Servicio de Recuperación de Cadena Hash para Verifactu

¿Cuándo usar este servicio?
---------------------------
1. Después de restaurar una copia de seguridad de la base de datos
2. Al migrar desde otro sistema de facturación
3. Si se detecta corrupción en la cadena hash

¿Cómo funciona?
---------------
La cadena hash es como un collar de perlas - cada factura está "atada"
a la anterior mediante un código único (hash). Si pierdes alguna perla
(factura), necesitas saber cuál era la última para poder continuar.

Este servicio te permite:
- Detectar si hay una ruptura en la cadena
- Consultar a AEAT cuál fue tu última factura enviada
- Recuperar el hash necesario para continuar facturando
"""

import logging
from datetime import datetime
from typing import Optional, Tuple, List
from dataclasses import dataclass
from enum import Enum
from django.utils import timezone
from django.db import transaction

logger = logging.getLogger('verifactu.recovery')


class RecoveryStatus(Enum):
    """Estados posibles de la recuperación."""
    SUCCESS = 'success'           # Recuperación exitosa
    NO_RECORDS = 'no_records'     # No hay registros en AEAT
    CONNECTION_ERROR = 'connection_error'  # Error de conexión
    INVALID_HASH = 'invalid_hash'  # Hash introducido no válido
    ALREADY_SYNCED = 'already_synced'  # Ya está sincronizado


@dataclass
class ChainStatus:
    """
    Estado actual de la cadena hash.

    Atributos:
        is_synced: True si la cadena local coincide con AEAT
        local_last_hash: Último hash en la base de datos local
        local_last_invoice: Última factura en local
        aeat_last_hash: Último hash en AEAT (si se consultó)
        aeat_last_invoice: Última factura en AEAT (si se consultó)
        gap_count: Número de facturas que faltan (si hay gap)
    """
    is_synced: bool
    local_last_hash: Optional[str] = None
    local_last_invoice: Optional[str] = None
    aeat_last_hash: Optional[str] = None
    aeat_last_invoice: Optional[str] = None
    gap_count: int = 0
    message: str = ''


@dataclass
class RecoveryResult:
    """
    Resultado de una operación de recuperación.

    Atributos:
        status: Estado de la recuperación
        recovered_hash: Hash recuperado (si éxito)
        recovered_invoice: Número de factura asociada al hash
        message: Mensaje descriptivo para el usuario
    """
    status: RecoveryStatus
    recovered_hash: Optional[str] = None
    recovered_invoice: Optional[str] = None
    message: str = ''


class ChainRecoveryService:
    """
    Servicio para recuperar la cadena hash cuando se pierde.

    Ejemplo de uso típico:
    ----------------------
    ```python
    # 1. Comprobar si hay problemas
    service = ChainRecoveryService()
    status = service.get_chain_status('B12345678')

    if not status.is_synced:
        print(f"⚠️ Cadena desincronizada!")
        print(f"Local: {status.local_last_invoice}")
        print(f"AEAT:  {status.aeat_last_invoice}")

        # 2. Recuperar desde AEAT
        result = service.recover_from_aeat('B12345678')

        if result.status == RecoveryStatus.SUCCESS:
            print(f"✅ Cadena recuperada: {result.recovered_hash}")
        else:
            print(f"❌ Error: {result.message}")
    ```

    Flujo visual:
    -------------
    ```
    [Tu base de datos]              [AEAT]
         F1 → F2                    F1 → F2 → F3 → F4
              ↓                                    ↓
         Hash B                               Hash D

    Problema: Tu siguiente factura usaría Hash B
              pero AEAT espera Hash D

    Solución: Consultar AEAT → Obtener Hash D → Usarlo
    ```
    """

    def __init__(self):
        """Inicializa el servicio de recuperación."""
        self._aeat_client = None

    def get_chain_status(self, issuer_nif: str) -> ChainStatus:
        """
        Obtiene el estado actual de la cadena hash.

        Compara lo que tienes en local con lo que hay en AEAT
        para detectar si hay desincronización.

        Args:
            issuer_nif: Tu NIF de empresa

        Returns:
            ChainStatus con el estado de la cadena
        """
        from verifactu.models import VerifactuRecord

        # Obtener último registro local
        local_last = VerifactuRecord.objects.filter(
            issuer_nif=issuer_nif,
            transmission_status='sent',
        ).order_by('-sequence_number').first()

        local_hash = local_last.record_hash if local_last else None
        local_invoice = local_last.invoice_number if local_last else None

        # Intentar consultar AEAT
        aeat_hash = None
        aeat_invoice = None
        gap_count = 0

        try:
            client = self._get_aeat_client()
            if client:
                response = client.query_last_records(issuer_nif, limit=1)
                if response.success and response.records:
                    aeat_record = response.records[0]
                    aeat_hash = aeat_record.record_hash
                    aeat_invoice = aeat_record.invoice_number
        except Exception as e:
            logger.warning(f"Could not query AEAT: {e}")

        # Determinar si está sincronizado
        if aeat_hash is None:
            # No pudimos consultar AEAT
            is_synced = True  # Asumimos que está bien
            message = "No se pudo verificar con AEAT"
        elif local_hash == aeat_hash:
            is_synced = True
            message = "Cadena sincronizada correctamente"
        elif local_hash is None and aeat_hash:
            is_synced = False
            gap_count = 1  # Al menos una factura
            message = "Base de datos vacía pero hay registros en AEAT"
        else:
            is_synced = False
            message = "Cadena desincronizada - se requiere recuperación"

        return ChainStatus(
            is_synced=is_synced,
            local_last_hash=local_hash,
            local_last_invoice=local_invoice,
            aeat_last_hash=aeat_hash,
            aeat_last_invoice=aeat_invoice,
            gap_count=gap_count,
            message=message,
        )

    def recover_from_aeat(self, issuer_nif: str) -> RecoveryResult:
        """
        Recupera el último hash consultando a AEAT.

        Este es el método preferido cuando tienes conexión a internet
        y un certificado válido configurado.

        Args:
            issuer_nif: Tu NIF de empresa

        Returns:
            RecoveryResult con el hash recuperado o error

        Ejemplo:
        --------
        ```python
        result = service.recover_from_aeat('B12345678')
        if result.status == RecoveryStatus.SUCCESS:
            # Guardar para uso futuro
            save_recovered_hash(result.recovered_hash)
        ```
        """
        from verifactu.models import VerifactuEvent

        logger.info(f"Attempting chain recovery from AEAT for {issuer_nif}")

        try:
            client = self._get_aeat_client()
            if not client:
                return RecoveryResult(
                    status=RecoveryStatus.CONNECTION_ERROR,
                    message="No hay cliente AEAT configurado. Verifica el certificado.",
                )

            response = client.query_last_records(issuer_nif, limit=1)

            if not response.success:
                return RecoveryResult(
                    status=RecoveryStatus.CONNECTION_ERROR,
                    message=f"Error al consultar AEAT: {response.message}",
                )

            if not response.records:
                return RecoveryResult(
                    status=RecoveryStatus.NO_RECORDS,
                    message="No hay registros en AEAT para este NIF. "
                           "Si es tu primera factura, no necesitas recuperar nada.",
                )

            last_record = response.records[0]

            # Guardar punto de recuperación
            self._save_recovery_point(
                issuer_nif=issuer_nif,
                recovered_hash=last_record.record_hash,
                invoice_number=last_record.invoice_number,
                source='aeat',
            )

            # Registrar evento
            VerifactuEvent.objects.create(
                event_type='info',
                description=f"Cadena recuperada desde AEAT. "
                           f"Último hash: {last_record.record_hash[:16]}...",
            )

            logger.info(f"Chain recovered successfully: {last_record.invoice_number}")

            return RecoveryResult(
                status=RecoveryStatus.SUCCESS,
                recovered_hash=last_record.record_hash,
                recovered_invoice=last_record.invoice_number,
                message=f"Cadena recuperada. Última factura: {last_record.invoice_number}",
            )

        except Exception as e:
            logger.error(f"Chain recovery failed: {e}")
            return RecoveryResult(
                status=RecoveryStatus.CONNECTION_ERROR,
                message=f"Error durante la recuperación: {e}",
            )

    def recover_manual(self, issuer_nif: str, last_hash: str) -> RecoveryResult:
        """
        Recupera la cadena introduciendo el hash manualmente.

        Usa este método cuando:
        - No tienes conexión a internet
        - El certificado no está configurado
        - Conoces el hash de otra fuente (ej: aplicación AEAT)

        Args:
            issuer_nif: Tu NIF de empresa
            last_hash: El hash SHA-256 de tu última factura (64 caracteres)

        Returns:
            RecoveryResult indicando éxito o error

        Ejemplo:
        --------
        ```python
        # Hash obtenido de la app AEAT o de un backup
        hash = "A1B2C3D4E5F6..."  # 64 caracteres hexadecimales
        result = service.recover_manual('B12345678', hash)
        ```
        """
        from verifactu.models import VerifactuEvent
        from .hash_service import HashService

        logger.info(f"Manual chain recovery for {issuer_nif}")

        # Validar formato del hash
        if not HashService.validate_hash_format(last_hash):
            return RecoveryResult(
                status=RecoveryStatus.INVALID_HASH,
                message="El hash no tiene el formato correcto. "
                       "Debe ser una cadena de 64 caracteres hexadecimales en mayúsculas.",
            )

        # Guardar punto de recuperación
        self._save_recovery_point(
            issuer_nif=issuer_nif,
            recovered_hash=last_hash,
            invoice_number=None,  # No conocemos el número
            source='manual',
        )

        # Registrar evento
        VerifactuEvent.objects.create(
            event_type='info',
            description=f"Cadena recuperada manualmente. "
                       f"Hash: {last_hash[:16]}...",
        )

        return RecoveryResult(
            status=RecoveryStatus.SUCCESS,
            recovered_hash=last_hash,
            message="Hash guardado correctamente. Las próximas facturas usarán este hash.",
        )

    def get_effective_last_hash(self, issuer_nif: str) -> str:
        """
        Obtiene el hash que debe usarse para la siguiente factura.

        Este método combina:
        1. Hash del último registro local (si existe)
        2. Hash recuperado (si hay punto de recuperación)

        Usa siempre este método antes de crear una nueva factura.

        Args:
            issuer_nif: Tu NIF de empresa

        Returns:
            Hash a usar como previous_hash (cadena vacía si es primera factura)
        """
        from verifactu.models import VerifactuRecord

        # Primero buscar en registros locales
        local_last = VerifactuRecord.objects.filter(
            issuer_nif=issuer_nif,
        ).order_by('-sequence_number').first()

        if local_last:
            return local_last.record_hash

        # Si no hay registros locales, buscar punto de recuperación
        recovery_point = self._get_recovery_point(issuer_nif)
        if recovery_point:
            return recovery_point['hash']

        # Primera factura
        return ''

    def _get_aeat_client(self):
        """Obtiene el cliente AEAT configurado."""
        if self._aeat_client is None:
            try:
                from verifactu.models import VerifactuConfig
                from .aeat_client import AEATClient, AEATEnvironment

                config = VerifactuConfig.get_config()
                if config and config.certificate_path:
                    env = (AEATEnvironment.PRODUCTION
                           if config.environment == 'production'
                           else AEATEnvironment.TESTING)
                    self._aeat_client = AEATClient(
                        certificate_path=config.certificate_path,
                        certificate_password=config.certificate_password or '',
                        environment=env,
                    )
            except Exception as e:
                logger.warning(f"Could not create AEAT client: {e}")

        return self._aeat_client

    def _save_recovery_point(
        self,
        issuer_nif: str,
        recovered_hash: str,
        invoice_number: Optional[str],
        source: str,
    ):
        """
        Guarda un punto de recuperación en la configuración.

        Este punto se usará si no hay registros locales.
        """
        from verifactu.models import VerifactuConfig

        config = VerifactuConfig.get_config()
        if config:
            # Guardar en un campo JSON o como atributo
            # Por ahora usamos el campo de metadata si existe
            config.save()

        # También guardamos en un archivo de respaldo
        import json
        import os

        recovery_file = os.path.join(
            os.path.dirname(__file__),
            '..',
            'recovery_points.json'
        )

        try:
            if os.path.exists(recovery_file):
                with open(recovery_file, 'r') as f:
                    data = json.load(f)
            else:
                data = {}

            data[issuer_nif] = {
                'hash': recovered_hash,
                'invoice_number': invoice_number,
                'source': source,
                'timestamp': timezone.now().isoformat(),
            }

            with open(recovery_file, 'w') as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            logger.warning(f"Could not save recovery point file: {e}")

    def _get_recovery_point(self, issuer_nif: str) -> Optional[dict]:
        """Obtiene un punto de recuperación guardado."""
        import json
        import os

        recovery_file = os.path.join(
            os.path.dirname(__file__),
            '..',
            'recovery_points.json'
        )

        try:
            if os.path.exists(recovery_file):
                with open(recovery_file, 'r') as f:
                    data = json.load(f)
                return data.get(issuer_nif)
        except Exception as e:
            logger.warning(f"Could not read recovery point: {e}")

        return None


# Singleton para acceso fácil
_recovery_service = None


def get_recovery_service() -> ChainRecoveryService:
    """Obtiene la instancia del servicio de recuperación."""
    global _recovery_service
    if _recovery_service is None:
        _recovery_service = ChainRecoveryService()
    return _recovery_service
