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
    path('records/<uuid:record_id>/', views.record_detail, name='record_detail'),

    # Settings
    path('settings/', views.settings_view, name='settings'),
    path('settings/change-mode/', views.change_mode, name='change_mode'),
    path('settings/save-software/', views.save_software_settings, name='save_software_settings'),
    path('settings/save-connection/', views.save_connection_settings, name='save_connection_settings'),

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
    path('api/upload-certificate/', views.upload_certificate, name='upload_certificate'),
]
