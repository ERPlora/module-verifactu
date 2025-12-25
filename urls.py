"""
URL configuration for Verifactu module.
"""

from django.urls import path
from . import views

app_name = 'verifactu'

urlpatterns = [
    # Dashboard
    path('', views.dashboard, name='dashboard'),

    # Records
    path('records/', views.records_list, name='records'),
    path('records/<int:record_id>/', views.record_detail, name='record_detail'),

    # Settings
    path('settings/', views.settings_view, name='settings'),

    # Contingency
    path('contingency/', views.contingency_view, name='contingency'),
    path('contingency/process/', views.process_queue, name='process_queue'),
    path('contingency/retry/<int:queue_id>/', views.retry_record, name='retry_record'),
    path('contingency/cancel/<int:queue_id>/', views.cancel_queue_entry, name='cancel_queue_entry'),

    # Events/Audit
    path('events/', views.events_list, name='events'),

    # Chain Recovery (Recuperación de cadena hash)
    path('recovery/', views.chain_recovery_view, name='recovery'),
    path('recovery/aeat/', views.recover_from_aeat, name='recover_from_aeat'),
    path('recovery/manual/', views.recover_manual, name='recover_manual'),

    # API endpoints
    path('api/health/', views.health_check, name='health_check'),
    path('api/verify-chain/', views.verify_chain, name='verify_chain'),
    path('api/test-connection/', views.test_connection, name='test_connection'),
    path('api/chain-status/', views.chain_status_api, name='chain_status'),
]
