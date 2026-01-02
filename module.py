"""
Verifactu Module Configuration

This file defines the module metadata and navigation for the Verifactu module.
Spanish electronic invoicing compliance (VERI*FACTU) - Real Decreto 1007/2023.
Used by the @module_view decorator to automatically render navigation tabs.
"""
from django.utils.translation import gettext_lazy as _

# Module Identification
MODULE_ID = "verifactu"
MODULE_NAME = _("Verifactu")
MODULE_ICON = "shield-checkmark-outline"
MODULE_VERSION = "1.0.0"
MODULE_CATEGORY = "localization"  # Changed from "legal" to more specific category

# Target Industries (business verticals this module is designed for)
# Note: Verifactu is mandatory for all businesses in Spain
MODULE_INDUSTRIES = [
    "retail",       # Retail stores
    "restaurant",   # Restaurants
    "bar",          # Bars & pubs
    "cafe",         # Cafes & bakeries
    "beauty",       # Beauty & wellness
    "consulting",   # Professional services
    "wholesale",    # Wholesale distributors
]

# Sidebar Menu Configuration
MENU = {
    "label": _("Verifactu"),
    "icon": "shield-checkmark-outline",
    "order": 35,
    "show": True,
}

# Internal Navigation (Tabs)
NAVIGATION = [
    {
        "id": "dashboard",
        "label": _("Dashboard"),
        "icon": "speedometer-outline",
        "view": "",
    },
    {
        "id": "records",
        "label": _("Records"),
        "icon": "document-text-outline",
        "view": "records",
    },
    {
        "id": "contingency",
        "label": _("Contingency"),
        "icon": "shield-checkmark-outline",
        "view": "contingency",
    },
    {
        "id": "settings",
        "label": _("Settings"),
        "icon": "settings-outline",
        "view": "settings",
    },
]

# Module Dependencies
DEPENDENCIES = ["invoicing>=1.0.0"]

# Default Settings
SETTINGS = {
    "enabled": True,
    "mode": "verifactu",
    "environment": "testing",
    "auto_transmit": True,
    "retry_interval_minutes": 5,
    "max_retries": 10,
}

# Permissions
PERMISSIONS = [
    "verifactu.view",
    "verifactu.manage",
    "verifactu.configure",
    "verifactu.transmit",
]

# Compliance Information
COMPLIANCE = {
    "regulations": [
        "Real Decreto 1007/2023",
        "Orden HAC/1177/2024",
    ],
    "deadline_software": "2025-07-29",
    "deadline_corporate": "2027-01-01",
    "deadline_autonomous": "2027-07-01",
}
