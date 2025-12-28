# Generated migration for reconciliation status fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('verifactu', '0002_add_mode_locking'),
    ]

    operations = [
        migrations.AddField(
            model_name='verifactuconfig',
            name='last_reconciliation_at',
            field=models.DateTimeField(
                blank=True,
                help_text='When the last reconciliation with AEAT was performed',
                null=True,
                verbose_name='Last Reconciliation',
            ),
        ),
        migrations.AddField(
            model_name='verifactuconfig',
            name='last_reconciliation_status',
            field=models.CharField(
                blank=True,
                help_text='Status of last reconciliation: success, mismatch_detected, failed, etc.',
                max_length=30,
                verbose_name='Reconciliation Status',
            ),
        ),
        migrations.AddField(
            model_name='verifactuconfig',
            name='last_reconciliation_message',
            field=models.TextField(
                blank=True,
                help_text='Detailed message from last reconciliation',
                verbose_name='Reconciliation Message',
            ),
        ),
    ]
