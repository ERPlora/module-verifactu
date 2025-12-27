"""
Views for Verifactu Module
Spanish electronic invoicing compliance (VERI*FACTU).
"""

import os
import json
from datetime import timedelta
from pathlib import Path

from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db.models import Count, Q
from django.conf import settings

# Import htmx_view decorator from hub core
import sys
from pathlib import Path as PathLib
hub_path = PathLib(__file__).parent.parent.parent / 'hub'
if str(hub_path) not in sys.path:
    sys.path.insert(0, str(hub_path))

from apps.core.htmx import htmx_view

from .models import VerifactuConfig, VerifactuRecord, VerifactuEvent, ContingencyQueue
from .services import ContingencyManager
from .services.contingency import get_contingency_manager


def is_demo_mode():
    """Check if Verifactu is running in demo mode."""
    return os.environ.get('VERIFACTU_DEMO_MODE', 'false').lower() in ('true', '1', 'yes')


@require_http_methods(["GET"])
@login_required
@htmx_view('verifactu/dashboard.html', 'verifactu/partials/dashboard_content.html')
def dashboard(request):
    """
    Verifactu dashboard - main entry point.
    Shows status overview, recent records, and alerts.
    """
    config = VerifactuConfig.get_config()
    contingency = get_contingency_manager()
    status = contingency.get_status()

    # Statistics
    today = timezone.now().date()
    month_start = today.replace(day=1)

    total_records = VerifactuRecord.objects.count()
    today_records = VerifactuRecord.objects.filter(
        generation_timestamp__date=today
    ).count()
    month_records = VerifactuRecord.objects.filter(
        generation_timestamp__date__gte=month_start
    ).count()
    pending_records = VerifactuRecord.objects.filter(
        status='pending'
    ).count()

    # Recent records
    recent_records = VerifactuRecord.objects.order_by('-generation_timestamp')[:10]

    # Recent events/alerts
    recent_events = VerifactuEvent.objects.filter(
        event_type__in=['error', 'alert']
    ).order_by('-timestamp')[:5]

    # Queue status
    queue_count = ContingencyQueue.objects.filter(
        status__in=['pending', 'retrying']
    ).count()

    demo_mode = is_demo_mode()

    return {
        'config': config,
        'status': status,
        'total_records': total_records,
        'today_records': today_records,
        'month_records': month_records,
        'pending_records': pending_records,
        'recent_records': recent_records,
        'recent_events': recent_events,
        'queue_count': queue_count,
        'is_configured': config is not None and config.certificate_path,
        'demo_mode': demo_mode,
    }


@require_http_methods(["GET"])
@login_required
@htmx_view('verifactu/records.html', 'verifactu/partials/records_content.html')
def records_list(request):
    """
    List all Verifactu records with filtering.
    """
    search = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', '')
    record_type = request.GET.get('type', '')

    records = VerifactuRecord.objects.all().order_by('-generation_timestamp')

    if search:
        records = records.filter(
            Q(invoice_number__icontains=search) |
            Q(issuer_name__icontains=search) |
            Q(issuer_nif__icontains=search)
        )

    if status_filter:
        records = records.filter(status=status_filter)

    if record_type:
        records = records.filter(record_type=record_type)

    # Handle HX-Target for table refresh (special case)
    if request.headers.get('HX-Target') == 'records-table-container':
        return render(request, 'verifactu/partials/records_table.html', {
            'records': records[:100],
            'search': search,
            'status_filter': status_filter,
            'record_type': record_type,
            'status_choices': VerifactuRecord.TransmissionStatus.choices,
            'type_choices': VerifactuRecord.RecordType.choices,
        })

    return {
        'records': records[:100],
        'search': search,
        'status_filter': status_filter,
        'record_type': record_type,
        'status_choices': VerifactuRecord.TransmissionStatus.choices,
        'type_choices': VerifactuRecord.RecordType.choices,
    }


@require_http_methods(["GET"])
@login_required
@htmx_view('verifactu/record_detail.html', 'verifactu/partials/record_detail_content.html')
def record_detail(request, record_id):
    """
    View details of a specific Verifactu record.
    """
    record = get_object_or_404(VerifactuRecord, id=record_id)

    # Get related events
    events = VerifactuEvent.objects.filter(record=record).order_by('-timestamp')

    # Generate QR code if available
    qr_data_uri = None
    try:
        from .services import QRService
        if QRService.is_available():
            qr_data_uri = QRService.generate_for_record(record)
    except Exception:
        pass

    return {
        'record': record,
        'events': events,
        'qr_data_uri': qr_data_uri,
    }


@require_http_methods(["GET", "POST"])
@login_required
@htmx_view('verifactu/settings.html', 'verifactu/partials/settings_content.html')
def settings_view(request):
    """
    Verifactu configuration settings.
    """
    config = VerifactuConfig.get_config()

    if request.method == 'POST':
        try:
            data = json.loads(request.body) if request.content_type == 'application/json' else request.POST

            if config is None:
                config = VerifactuConfig()

            # Update configuration
            config.software_name = data.get('software_name', config.software_name)
            config.software_id = data.get('software_id', config.software_id)
            config.software_version = data.get('software_version', config.software_version)
            config.software_nif = data.get('software_nif', config.software_nif)
            config.environment = data.get('environment', config.environment)
            config.auto_submit = data.get('auto_submit', 'false').lower() == 'true'

            # Certificate handling would require file upload
            # For now, just path configuration
            if 'certificate_path' in data:
                config.certificate_path = data['certificate_path']

            config.save()

            return JsonResponse({
                'success': True,
                'message': 'Configuración guardada correctamente',
            })

        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e),
            }, status=400)

    # GET request
    demo_mode = is_demo_mode()

    # Get mode lock info
    mode_lock_info = config.get_mode_lock_info() if config else {'locked': False, 'can_change': True}

    # Get software version from module.json
    module_json_path = Path(__file__).parent / 'module.json'
    software_version = '1.0.0'
    try:
        with open(module_json_path) as f:
            module_data = json.load(f)
            software_version = module_data.get('version', '1.0.0')
    except Exception:
        pass

    return {
        'config': config,
        'environments': [
            ('testing', 'Pruebas (AEAT Test)'),
            ('production', 'Producción'),
        ],
        'demo_mode': demo_mode,
        'mode_lock_info': mode_lock_info,
        'modes': VerifactuConfig.Mode.choices,
        'software_version': software_version,
    }


@require_http_methods(["POST"])
@login_required
def change_mode(request):
    """
    Change Verifactu operating mode (VERI*FACTU or NO VERI*FACTU).
    Only allowed if mode is not locked for current fiscal year.
    """
    config = VerifactuConfig.get_config()

    if not config.can_change_mode():
        return JsonResponse({
            'success': False,
            'error': 'El modo está bloqueado para este año fiscal. '
                     'Una vez creada la primera factura o ticket, el modo no puede cambiar hasta el próximo año.',
        }, status=403)

    try:
        data = json.loads(request.body) if request.content_type == 'application/json' else request.POST
        new_mode = data.get('mode', '')

        if new_mode not in [VerifactuConfig.Mode.VERIFACTU, VerifactuConfig.Mode.NO_VERIFACTU]:
            return JsonResponse({
                'success': False,
                'error': 'Modo inválido',
            }, status=400)

        old_mode = config.mode
        config.mode = new_mode
        config.save()

        # Log the change
        VerifactuEvent.log(
            event_type='config_changed',
            message=f'Modo cambiado de {old_mode} a {new_mode}',
            severity='warning',
            details={'old_mode': old_mode, 'new_mode': new_mode}
        )

        return JsonResponse({
            'success': True,
            'message': f'Modo cambiado a {config.get_mode_display()}',
            'mode': new_mode,
            'mode_display': config.get_mode_display(),
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e),
        }, status=400)


@require_http_methods(["POST"])
@login_required
def upload_certificate(request):
    """
    Upload and save a PKCS#12 certificate file.
    The certificate is saved in MEDIA_ROOT/verifactu/certificates/
    """
    if 'certificate' not in request.FILES:
        return JsonResponse({
            'success': False,
            'error': 'No se ha proporcionado ningún archivo',
        }, status=400)

    certificate_file = request.FILES['certificate']
    password = request.POST.get('password', '')

    # Validate file extension
    if not certificate_file.name.lower().endswith(('.p12', '.pfx')):
        return JsonResponse({
            'success': False,
            'error': 'El archivo debe ser un certificado PKCS#12 (.p12 o .pfx)',
        }, status=400)

    # Create certificates directory in media
    certificates_dir = os.path.join(settings.MEDIA_ROOT, 'verifactu', 'certificates')
    os.makedirs(certificates_dir, exist_ok=True)

    # Generate unique filename
    import uuid
    filename = f"certificate_{uuid.uuid4().hex[:8]}.p12"
    filepath = os.path.join(certificates_dir, filename)

    # Save the file
    try:
        with open(filepath, 'wb') as f:
            for chunk in certificate_file.chunks():
                f.write(chunk)

        # Validate the certificate (try to load it)
        try:
            from cryptography.hazmat.primitives.serialization import pkcs12
            from cryptography import x509

            with open(filepath, 'rb') as f:
                cert_data = f.read()

            # Try to load the certificate with the password
            private_key, certificate, additional_certs = pkcs12.load_key_and_certificates(
                cert_data,
                password.encode() if password else None
            )

            if certificate is None:
                os.remove(filepath)
                return JsonResponse({
                    'success': False,
                    'error': 'No se pudo leer el certificado. Verifica la contraseña.',
                }, status=400)

            # Get certificate expiry date
            expiry_date = certificate.not_valid_after_utc.date()

            # Get certificate subject (for display)
            subject = certificate.subject.rfc4514_string()

        except ImportError:
            # cryptography library not available, skip validation
            expiry_date = None
            subject = None

        except Exception as e:
            os.remove(filepath)
            return JsonResponse({
                'success': False,
                'error': f'Error al validar el certificado: {str(e)}',
            }, status=400)

        # Update configuration
        config = VerifactuConfig.get_config()
        config.certificate_path = filepath
        config.certificate_password = password  # Note: Should be encrypted in production
        if expiry_date:
            config.certificate_expiry = expiry_date
        config.save()

        # Log the event
        VerifactuEvent.log(
            event_type='config_changed',
            message=f'Certificado cargado: {certificate_file.name}',
            severity='info',
            details={'subject': subject, 'expiry': str(expiry_date) if expiry_date else None}
        )

        return JsonResponse({
            'success': True,
            'message': 'Certificado cargado correctamente',
            'certificate_path': filepath,
            'expiry_date': str(expiry_date) if expiry_date else None,
            'subject': subject,
        })

    except Exception as e:
        # Clean up on error
        if os.path.exists(filepath):
            os.remove(filepath)
        return JsonResponse({
            'success': False,
            'error': f'Error al guardar el certificado: {str(e)}',
        }, status=500)


@require_http_methods(["GET"])
@login_required
@htmx_view('verifactu/contingency.html', 'verifactu/partials/contingency_content.html')
def contingency_view(request):
    """
    Contingency management and queue status.
    """
    contingency = get_contingency_manager()
    status = contingency.get_status()

    # Get queued records
    queued = ContingencyQueue.objects.filter(
        status__in=['pending', 'retrying']
    ).select_related('record').order_by('priority', 'queued_at')[:50]

    # Get failed records
    failed = ContingencyQueue.objects.filter(
        status='failed'
    ).select_related('record').order_by('-last_attempt_at')[:20]

    # Recent events
    events = VerifactuEvent.objects.order_by('-timestamp')[:20]

    return {
        'status': status,
        'queued': queued,
        'failed': failed,
        'events': events,
    }


@require_http_methods(["POST"])
@login_required
def process_queue(request):
    """
    Manually trigger queue processing.
    """
    contingency = get_contingency_manager()

    try:
        successful, failed = contingency.process_queue()

        return JsonResponse({
            'success': True,
            'message': f'Procesados: {successful} exitosos, {failed} fallidos',
            'successful': successful,
            'failed': failed,
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e),
        }, status=500)


@require_http_methods(["POST"])
@login_required
def verify_chain(request):
    """
    Verify hash chain integrity.
    In demo mode, returns a simulated valid chain.
    Returns HTML partial for HTMX requests, JSON for API calls.
    """
    is_valid = False
    message = ''

    # Demo mode - simulate valid chain
    if is_demo_mode():
        record_count = VerifactuRecord.objects.count()
        is_valid = True
        message = f'Cadena verificada (Modo Demo): {record_count} registros'
    else:
        contingency = get_contingency_manager()

        try:
            is_valid, error_message = contingency.verify_hash_chain()
            message = error_message or 'Cadena de hash verificada correctamente'
        except Exception as e:
            is_valid = False
            message = str(e)

    # HTMX request - return HTML partial
    if request.headers.get('HX-Request'):
        return render(request, 'verifactu/partials/result_badge.html', {
            'success': is_valid,
            'message': message,
        })

    # API request - return JSON
    return JsonResponse({
        'success': True,
        'is_valid': is_valid,
        'message': message,
        'demo_mode': is_demo_mode(),
    })


@require_http_methods(["POST"])
@login_required
def test_connection(request):
    """
    Test connection to AEAT.
    In demo mode, simulates a successful connection.
    Returns HTML partial for HTMX requests, JSON for API calls.
    """
    success = False
    message = ''

    # Demo mode - simulate successful connection
    if is_demo_mode():
        success = True
        message = 'Conexión simulada exitosa (Modo Demo)'
    else:
        config = VerifactuConfig.get_config()

        if not config or not config.certificate_path:
            success = False
            message = 'No hay certificado configurado. Carga un certificado primero.'
        else:
            try:
                from .services.aeat_client import AEATClient, AEATEnvironment

                env = AEATEnvironment.PRODUCTION if config.environment == 'production' else AEATEnvironment.TESTING

                with AEATClient(
                    certificate_path=config.certificate_path,
                    certificate_password=config.certificate_password,
                    environment=env,
                ) as client:
                    success, message = client.test_connection()

            except Exception as e:
                success = False
                message = str(e)

    # HTMX request - return HTML partial
    if request.headers.get('HX-Request'):
        return render(request, 'verifactu/partials/result_badge.html', {
            'success': success,
            'message': message,
        })

    # API request - return JSON
    return JsonResponse({
        'success': success,
        'message': message,
        'demo_mode': is_demo_mode(),
    })


@require_http_methods(["GET"])
@login_required
def health_check(request):
    """
    System health check endpoint.
    """
    contingency = get_contingency_manager()
    is_healthy, message = contingency.check_health()
    status = contingency.get_status()

    return JsonResponse({
        'healthy': is_healthy,
        'message': message,
        'mode': status.mode_value,
        'queue_size': status.queue_size,
        'can_create_records': status.can_create_records,
    })


@require_http_methods(["GET"])
@login_required
@htmx_view('verifactu/events.html', 'verifactu/partials/events_content.html')
def events_list(request):
    """
    List all Verifactu events/audit log.
    """
    event_type = request.GET.get('type', '')

    events = VerifactuEvent.objects.all().order_by('-timestamp')

    if event_type:
        events = events.filter(event_type=event_type)

    return {
        'events': events[:100],
        'event_type': event_type,
        'type_choices': VerifactuEvent.TYPE_CHOICES,
    }


@require_http_methods(["POST"])
@login_required
def retry_record(request, queue_id):
    """
    Manually retry a failed queue entry.
    """
    queue_entry = get_object_or_404(ContingencyQueue, id=queue_id)

    queue_entry.status = 'pending'
    queue_entry.retry_count = 0
    queue_entry.next_retry = timezone.now()
    queue_entry.save()

    return JsonResponse({
        'success': True,
        'message': 'Registro añadido a la cola de reintentos',
    })


@require_http_methods(["POST"])
@login_required
def cancel_queue_entry(request, queue_id):
    """
    Cancel a queued record (mark as failed).
    """
    queue_entry = get_object_or_404(ContingencyQueue, id=queue_id)

    queue_entry.status = 'cancelled'
    queue_entry.save()

    VerifactuEvent.objects.create(
        event_type='info',
        description=f'Queue entry {queue_id} cancelled manually',
        record=queue_entry.record,
    )

    return JsonResponse({
        'success': True,
        'message': 'Entrada de cola cancelada',
    })


# ============================================
# RECUPERACIÓN DE CADENA HASH
# ============================================

@require_http_methods(["GET"])
@login_required
@htmx_view('verifactu/recovery.html', 'verifactu/partials/recovery_content.html')
def chain_recovery_view(request):
    """
    Vista de recuperación de cadena hash.

    Muestra el estado actual de la cadena y permite:
    - Consultar AEAT para obtener el último hash
    - Introducir un hash manualmente
    """
    from .services.recovery_service import get_recovery_service

    config = VerifactuConfig.get_config()
    recovery_service = get_recovery_service()

    # Obtener NIF del emisor
    issuer_nif = config.software_nif if config else ''

    # Obtener estado de la cadena
    chain_status = None
    if issuer_nif:
        try:
            chain_status = recovery_service.get_chain_status(issuer_nif)
        except Exception as e:
            chain_status = None

    return {
        'config': config,
        'issuer_nif': issuer_nif,
        'chain_status': chain_status,
    }


@require_http_methods(["POST"])
@login_required
def recover_from_aeat(request):
    """
    Recupera la cadena hash consultando a AEAT.

    POST /modules/verifactu/recovery/aeat/

    Respuesta JSON:
    {
        "success": true,
        "recovered_hash": "ABC123...",
        "recovered_invoice": "F2024-001",
        "message": "Cadena recuperada correctamente"
    }
    """
    from .services.recovery_service import get_recovery_service, RecoveryStatus

    config = VerifactuConfig.get_config()
    if not config or not config.software_nif:
        return JsonResponse({
            'success': False,
            'error': 'No hay NIF configurado. Ve a Configuración primero.',
        }, status=400)

    recovery_service = get_recovery_service()

    try:
        result = recovery_service.recover_from_aeat(config.software_nif)

        return JsonResponse({
            'success': result.status == RecoveryStatus.SUCCESS,
            'status': result.status.value,
            'recovered_hash': result.recovered_hash,
            'recovered_invoice': result.recovered_invoice,
            'message': result.message,
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e),
        }, status=500)


@require_http_methods(["POST"])
@login_required
def recover_manual(request):
    """
    Recupera la cadena hash manualmente.

    POST /modules/verifactu/recovery/manual/
    Body: {"hash": "ABC123..."}

    Respuesta JSON:
    {
        "success": true,
        "message": "Hash guardado correctamente"
    }
    """
    from .services.recovery_service import get_recovery_service, RecoveryStatus

    config = VerifactuConfig.get_config()
    if not config or not config.software_nif:
        return JsonResponse({
            'success': False,
            'error': 'No hay NIF configurado. Ve a Configuración primero.',
        }, status=400)

    try:
        data = json.loads(request.body)
        manual_hash = data.get('hash', '').strip().upper()

        if not manual_hash:
            return JsonResponse({
                'success': False,
                'error': 'No se proporcionó ningún hash',
            }, status=400)

        recovery_service = get_recovery_service()
        result = recovery_service.recover_manual(config.software_nif, manual_hash)

        return JsonResponse({
            'success': result.status == RecoveryStatus.SUCCESS,
            'status': result.status.value,
            'message': result.message,
        })

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'JSON inválido',
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e),
        }, status=500)


@require_http_methods(["GET"])
@login_required
def chain_status_api(request):
    """
    API para obtener el estado de la cadena hash.

    GET /modules/verifactu/api/chain-status/

    Respuesta JSON:
    {
        "is_synced": true,
        "local_last_hash": "ABC...",
        "local_last_invoice": "F2024-001",
        "aeat_last_hash": "ABC...",
        "aeat_last_invoice": "F2024-001",
        "message": "Cadena sincronizada"
    }
    """
    from .services.recovery_service import get_recovery_service

    config = VerifactuConfig.get_config()
    if not config or not config.software_nif:
        return JsonResponse({
            'success': False,
            'error': 'No hay NIF configurado',
        }, status=400)

    try:
        recovery_service = get_recovery_service()
        status = recovery_service.get_chain_status(config.software_nif)

        return JsonResponse({
            'success': True,
            'is_synced': status.is_synced,
            'local_last_hash': status.local_last_hash,
            'local_last_invoice': status.local_last_invoice,
            'aeat_last_hash': status.aeat_last_hash,
            'aeat_last_invoice': status.aeat_last_invoice,
            'gap_count': status.gap_count,
            'message': status.message,
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e),
        }, status=500)
