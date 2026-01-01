"""
Pytest configuration for verifactu module tests.

This conftest ensures Django is properly configured when running tests
from within the module directory.
"""
import os
import sys
from pathlib import Path

# Ensure Django settings are configured before any imports
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Add the hub directory to Python path
HUB_DIR = Path(__file__).resolve().parent.parent.parent.parent / 'hub'
if str(HUB_DIR) not in sys.path:
    sys.path.insert(0, str(HUB_DIR))

# Add the modules directory to Python path
MODULES_DIR = Path(__file__).resolve().parent.parent.parent
if str(MODULES_DIR) not in sys.path:
    sys.path.insert(0, str(MODULES_DIR))

# Now setup Django
import django
django.setup()

# Disable debug toolbar during tests to avoid namespace errors
from django.conf import settings
if 'debug_toolbar' in settings.INSTALLED_APPS:
    settings.INSTALLED_APPS = [
        app for app in settings.INSTALLED_APPS if app != 'debug_toolbar'
    ]
if hasattr(settings, 'MIDDLEWARE'):
    settings.MIDDLEWARE = [
        m for m in settings.MIDDLEWARE if 'debug_toolbar' not in m
    ]

# Import pytest and fixtures
import pytest
from decimal import Decimal
from django.test import Client

from apps.accounts.models import LocalUser
from apps.configuration.models import StoreConfig


@pytest.fixture
def client():
    """Create test client."""
    return Client()


@pytest.fixture
def local_user(db):
    """Create a test user."""
    from django.contrib.auth.hashers import make_password
    return LocalUser.objects.create(
        name="Test User",
        email="test@example.com",
        pin_hash=make_password("1234"),
        role="admin",
        is_active=True
    )


@pytest.fixture
def store_config(db):
    """Create store configuration (marks hub as configured)."""
    config = StoreConfig.get_config()
    config.is_configured = True
    config.name = 'Test Store'
    config.save()
    return config


@pytest.fixture
def auth_client(client, local_user, store_config):
    """Create authenticated test client with session."""
    session = client.session
    session['local_user_id'] = str(local_user.id)
    session['user_name'] = local_user.name
    session['user_email'] = local_user.email
    session['user_role'] = local_user.role
    session['store_config_checked'] = True
    session.save()
    return client
