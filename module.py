"""
Verifactu Module Configuration

Spanish fiscal compliance (Verifactu/TicketBAI).
"""
from django.utils.translation import gettext_lazy as _

MODULE_ID = "verifactu"
MODULE_NAME = _("Verifactu")
MODULE_ICON = "shield-checkmark-outline"
MODULE_VERSION = "1.0.0"
MODULE_CATEGORY = "fiscal"

MODULE_INDUSTRIES = ["retail", "restaurant", "bar", "cafe", "beauty", "healthcare"]

MENU = {
    "label": _("Verifactu"),
    "icon": "shield-checkmark-outline",
    "order": 80,
    "show": True,
}

NAVIGATION = [
    {"id": "dashboard", "label": _("Overview"), "icon": "grid-outline", "view": ""},
    {"id": "records", "label": _("Records"), "icon": "document-text-outline", "view": "records"},
    {"id": "events", "label": _("Events"), "icon": "pulse-outline", "view": "events"},
    {"id": "settings", "label": _("Settings"), "icon": "settings-outline", "view": "settings"},
]

DEPENDENCIES = []

SETTINGS = {
    "enabled": False,
    "test_mode": True,
    "auto_submit": True,
}

PERMISSIONS = [
    ("view_record", _("Can view records")),
    ("submit_record", _("Can submit records")),
    ("cancel_record", _("Can cancel records")),
    ("view_event", _("Can view events")),
    ("view_settings", _("Can view settings")),
    ("change_settings", _("Can change settings")),
    ("configure_certificates", _("Can configure certificates")),
]

ROLE_PERMISSIONS = {
    "admin": ["*"],
    "manager": [
        "view_record", "submit_record", "cancel_record",
        "view_event", "view_settings",
    ],
    "employee": ["view_record", "view_event"],
}
