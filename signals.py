"""
Signals for Verifactu module.

Handles automatic reconciliation when certificate is configured.
"""

import logging
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

logger = logging.getLogger('verifactu.signals')


@receiver(pre_save, sender='verifactu.VerifactuConfig')
def capture_previous_certificate_state(sender, instance, **kwargs):
    """
    Capture the previous certificate state before save.

    This allows us to detect when a certificate is configured
    for the first time or changed.
    """
    if instance.pk:
        try:
            previous = sender.objects.get(pk=instance.pk)
            instance._previous_certificate_path = previous.certificate_path
            instance._previous_certificate_password = previous.certificate_password
        except sender.DoesNotExist:
            instance._previous_certificate_path = None
            instance._previous_certificate_password = None
    else:
        instance._previous_certificate_path = None
        instance._previous_certificate_password = None


@receiver(post_save, sender='verifactu.VerifactuConfig')
def trigger_reconciliation_on_certificate_config(sender, instance, created, **kwargs):
    """
    Trigger reconciliation when certificate is configured.

    Runs when:
    1. Certificate path and password are set for the first time
    2. Certificate is changed (different path or password)

    Does NOT run when:
    - Certificate fields are cleared
    - Other fields are updated without certificate changes
    """
    # Get previous state
    previous_path = getattr(instance, '_previous_certificate_path', None)
    previous_password = getattr(instance, '_previous_certificate_password', None)

    current_path = instance.certificate_path
    current_password = instance.certificate_password

    # Check if certificate was just configured
    certificate_was_empty = not previous_path or not previous_password
    certificate_is_now_set = current_path and current_password
    certificate_changed = (
        previous_path != current_path or
        previous_password != current_password
    )

    should_reconcile = (
        certificate_is_now_set and
        (certificate_was_empty or certificate_changed)
    )

    if not should_reconcile:
        return

    logger.info("Certificate configured - triggering reconciliation")

    # Run reconciliation in background to not block the save
    # In production, this should be a Celery task
    try:
        from verifactu.services.reconciliation_service import reconcile_on_certificate_config
        result = reconcile_on_certificate_config()

        if result:
            logger.info(f"Reconciliation completed: {result.status.value}")

            # Update reconciliation status on config
            _update_reconciliation_status(instance, result)

    except Exception as e:
        logger.exception(f"Reconciliation failed: {e}")


def _update_reconciliation_status(config, result):
    """
    Update VerifactuConfig with reconciliation result.

    Uses update() to avoid triggering signals again.
    """
    from django.utils import timezone
    from verifactu.models import VerifactuConfig as ConfigModel

    ConfigModel.objects.filter(pk=config.pk).update(
        last_reconciliation_at=timezone.now(),
        last_reconciliation_status=result.status.value,
        last_reconciliation_message=result.message,
        updated_at=timezone.now(),
    )
