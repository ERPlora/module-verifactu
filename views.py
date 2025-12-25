"""
Views for Verifactu Module
Spanish electronic invoicing compliance (VERI*FACTU).
"""

from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db.models import Count, Q
from datetime import timedelta
import json

from .models import VerifactuConfig, VerifactuRecord, VerifactuEvent, ContingencyQueue
from .services import ContingencyManager
from .services.contingency import get_contingency_manager


@require_http_methods(["GET"])
@login_required
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
        transmission_status='pending'
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

    context = {
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
    }

    if request.headers.get('HX-Request'):
        return render(request, 'verifactu/partials/dashboard_content.html', context)
    return render(request, 'verifactu/dashboard.html', context)


@require_http_methods(["GET"])
@login_required
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
        records = records.filter(transmission_status=status_filter)

    if record_type:
        records = records.filter(record_type=record_type)

    context = {
        'records': records[:100],
        'search': search,
        'status_filter': status_filter,
        'record_type': record_type,
        'status_choices': VerifactuRecord.STATUS_CHOICES,
        'type_choices': VerifactuRecord.TYPE_CHOICES,
    }

    if request.headers.get('HX-Target') == 'records-table-container':
        return render(request, 'verifactu/partials/records_table.html', context)

    if request.headers.get('HX-Request'):
        return render(request, 'verifactu/partials/records_content.html', context)
    return render(request, 'verifactu/records.html', context)


@require_http_methods(["GET"])
@login_required
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

    context = {
        'record': record,
        'events': events,
        'qr_data_uri': qr_data_uri,
    }

    if request.headers.get('HX-Request'):
        return render(request, 'verifactu/partials/record_detail_content.html', context)
    return render(request, 'verifactu/record_detail.html', context)


@require_http_methods(["GET", "POST"])
@login_required
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
    context = {
        'config': config,
        'environments': [
            ('testing', 'Pruebas (AEAT Test)'),
            ('production', 'Producción'),
        ],
    }

    if request.headers.get('HX-Request'):
        return render(request, 'verifactu/partials/settings_content.html', context)
    return render(request, 'verifactu/settings.html', context)


@require_http_methods(["GET"])
@login_required
def contingency_view(request):
    """
    Contingency management and queue status.
    """
    contingency = get_contingency_manager()
    status = contingency.get_status()

    # Get queued records
    queued = ContingencyQueue.objects.filter(
        status__in=['pending', 'retrying']
    ).select_related('record').order_by('priority', 'created_at')[:50]

    # Get failed records
    failed = ContingencyQueue.objects.filter(
        status='failed'
    ).select_related('record').order_by('-updated_at')[:20]

    # Recent events
    events = VerifactuEvent.objects.order_by('-timestamp')[:20]

    context = {
        'status': status,
        'queued': queued,
        'failed': failed,
        'events': events,
    }

    if request.headers.get('HX-Request'):
        return render(request, 'verifactu/partials/contingency_content.html', context)
    return render(request, 'verifactu/contingency.html', context)


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
    """
    contingency = get_contingency_manager()

    try:
        is_valid, error_message = contingency.verify_hash_chain()

        return JsonResponse({
            'success': True,
            'is_valid': is_valid,
            'message': error_message or 'Cadena de hash verificada correctamente',
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e),
        }, status=500)


@require_http_methods(["POST"])
@login_required
def test_connection(request):
    """
    Test connection to AEAT.
    """
    config = VerifactuConfig.get_config()

    if not config or not config.certificate_path:
        return JsonResponse({
            'success': False,
            'error': 'No hay certificado configurado',
        }, status=400)

    try:
        from .services import AEATClient
        from .services.aeat_client import AEATEnvironment

        env = AEATEnvironment.PRODUCTION if config.environment == 'production' else AEATEnvironment.TESTING

        with AEATClient(
            certificate_path=config.certificate_path,
            certificate_password=config.certificate_password,
            environment=env,
        ) as client:
            success, message = client.test_connection()

        return JsonResponse({
            'success': success,
            'message': message,
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e),
        }, status=500)


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
        'mode': status.mode.value,
        'queue_size': status.queue_size,
        'can_create_records': status.can_create_records,
    })


@require_http_methods(["GET"])
@login_required
def events_list(request):
    """
    List all Verifactu events/audit log.
    """
    event_type = request.GET.get('type', '')

    events = VerifactuEvent.objects.all().order_by('-timestamp')

    if event_type:
        events = events.filter(event_type=event_type)

    context = {
        'events': events[:100],
        'event_type': event_type,
        'type_choices': VerifactuEvent.TYPE_CHOICES,
    }

    if request.headers.get('HX-Request'):
        return render(request, 'verifactu/partials/events_content.html', context)
    return render(request, 'verifactu/events.html', context)


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

    context = {
        'config': config,
        'issuer_nif': issuer_nif,
        'chain_status': chain_status,
    }

    if request.headers.get('HX-Request'):
        return render(request, 'verifactu/partials/recovery_content.html', context)
    return render(request, 'verifactu/recovery.html', context)


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
