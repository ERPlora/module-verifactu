import logging
from django.apps import AppConfig

logger = logging.getLogger('verifactu')


class VerifactuConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'verifactu'
    verbose_name = 'Verifactu'

    def ready(self):
        """
        Register extension points for the Verifactu module.

        This module LISTENS to signals:
        - invoice_created: Create Verifactu record for new invoices
        - sale_completed: Create simplified invoice record for tickets

        This module USES hooks:
        - invoicing.filter_lines: Add Verifactu hash to invoice data
        - invoicing.filter_totals: Validate totals match Verifactu record

        This module USES slots:
        - invoicing.footer: Inject QR code and Verifactu info

        This module EMITS signals:
        - (none currently, but could emit verifactu_record_created, etc.)
        """
        # Import local signals to register them
        from verifactu import signals  # noqa: F401

        # Register extension points
        self._register_signal_handlers()
        self._register_hooks()
        self._register_slots()

    def _register_signal_handlers(self):
        """Register handlers for signals from other modules."""
        from django.dispatch import receiver
        from apps.core.signals import invoice_created, sale_completed

        @receiver(invoice_created)
        def on_invoice_created(sender, invoice, sale, user, **kwargs):
            """
            Create Verifactu record when invoice is created.

            This is the main integration point - every invoice must have
            a corresponding Verifactu record for compliance.
            """
            try:
                self._create_verifactu_record_for_invoice(invoice, user)
            except Exception as e:
                logger.exception(f"Failed to create Verifactu record for invoice {invoice.id}: {e}")

        @receiver(sale_completed)
        def on_sale_completed(sender, sale, user, **kwargs):
            """
            Create Verifactu record for simplified invoices (tickets).

            When a sale is completed without a formal invoice, we still need
            to create a Verifactu record if the sale requires it.
            """
            try:
                self._create_verifactu_record_for_sale(sale, user)
            except Exception as e:
                logger.exception(f"Failed to create Verifactu record for sale {sale.id}: {e}")

    def _register_hooks(self):
        """Register callbacks for hooks from other modules."""
        from apps.core.hooks import hooks

        # Hook into invoicing to add Verifactu data before invoice is finalized
        hooks.add_filter(
            'invoicing.filter_lines',
            self._add_verifactu_hash_to_lines,
            module_id='verifactu',
            priority=100  # Run late to ensure all other modifications are done
        )

        # Hook into invoicing to validate totals match Verifactu requirements
        hooks.add_filter(
            'invoicing.filter_totals',
            self._validate_verifactu_totals,
            module_id='verifactu',
            priority=100
        )

    def _register_slots(self):
        """Register content for slots in other modules."""
        from apps.core.slots import slots

        # Inject QR code and Verifactu info in invoice footer
        slots.register(
            'invoicing.footer',
            template='verifactu/partials/invoice_qr.html',
            context_fn=self._get_qr_context,
            module_id='verifactu',
            priority=50  # Show QR prominently
        )

        # Also register for invoice header if needed for certificate info
        slots.register(
            'invoicing.header',
            template='verifactu/partials/verifactu_badge.html',
            context_fn=self._get_badge_context,
            module_id='verifactu',
            priority=90  # Show at end of header
        )

    # =========================================================================
    # Signal Handlers Implementation
    # =========================================================================

    def _create_verifactu_record_for_invoice(self, invoice, user):
        """
        Create a Verifactu record for a formal invoice.

        Args:
            invoice: Invoice model instance from invoicing module
            user: User who created the invoice
        """
        from .models import VerifactuConfig as VConfig, VerifactuRecord

        config = VConfig.get_config()
        if not config.enabled:
            logger.debug("Verifactu disabled, skipping record creation")
            return None

        # Get the last record for hash chain
        last_record = VerifactuRecord.objects.order_by('-sequence_number').first()
        previous_hash = last_record.record_hash if last_record else ''
        sequence_number = (last_record.sequence_number + 1) if last_record else 1
        is_first = sequence_number == 1

        # Create the record
        record = VerifactuRecord.objects.create(
            record_type=VerifactuRecord.RecordType.ALTA,
            sequence_number=sequence_number,
            invoice_id=invoice.id,
            issuer_nif=getattr(invoice, 'issuer_nif', ''),
            issuer_name=getattr(invoice, 'issuer_name', ''),
            invoice_number=str(invoice.number),
            invoice_date=invoice.date,
            invoice_type=self._get_invoice_type(invoice),
            description=getattr(invoice, 'description', '')[:500],
            base_amount=invoice.base_amount,
            tax_rate=getattr(invoice, 'tax_rate', 21),
            tax_amount=invoice.tax_amount,
            total_amount=invoice.total_amount,
            previous_hash=previous_hash,
            is_first_record=is_first,
            created_by=user.id if user else None
        )

        logger.info(f"Created Verifactu record {record.id} for invoice {invoice.number}")
        return record

    def _create_verifactu_record_for_sale(self, sale, user):
        """
        Create a Verifactu record for a simplified invoice (ticket).

        Only creates a record if:
        - Verifactu is enabled
        - Sale doesn't already have an associated invoice
        - Sale amount exceeds threshold requiring Verifactu

        Args:
            sale: Sale model instance from sales module
            user: User who completed the sale
        """
        from .models import VerifactuConfig as VConfig, VerifactuRecord

        config = VConfig.get_config()
        if not config.enabled:
            return None

        # Check if sale already has an invoice (invoice_created will handle it)
        if hasattr(sale, 'invoice') and sale.invoice:
            logger.debug(f"Sale {sale.id} has invoice, skipping direct Verifactu record")
            return None

        # Get issuer info from StoreConfig
        try:
            from apps.configuration.models import StoreConfig
            store = StoreConfig.get_config()
            issuer_nif = store.tax_id or ''
            issuer_name = store.name or 'Unknown'
        except Exception:
            issuer_nif = ''
            issuer_name = 'Unknown'

        # Get the last record for hash chain
        last_record = VerifactuRecord.objects.order_by('-sequence_number').first()
        previous_hash = last_record.record_hash if last_record else ''
        sequence_number = (last_record.sequence_number + 1) if last_record else 1
        is_first = sequence_number == 1

        # Create simplified invoice record (F2)
        record = VerifactuRecord.objects.create(
            record_type=VerifactuRecord.RecordType.ALTA,
            sequence_number=sequence_number,
            invoice_id=None,  # No formal invoice
            issuer_nif=issuer_nif,
            issuer_name=issuer_name,
            invoice_number=f"T-{sale.id}",  # Ticket prefix
            invoice_date=sale.created_at.date(),
            invoice_type=VerifactuRecord.InvoiceType.F2,  # Simplified
            description=f"Ticket de venta {sale.id}",
            base_amount=sale.subtotal,
            tax_rate=getattr(sale, 'tax_rate', 21),
            tax_amount=sale.tax_amount,
            total_amount=sale.total,
            previous_hash=previous_hash,
            is_first_record=is_first,
            created_by=user.id if user else None
        )

        logger.info(f"Created Verifactu record {record.id} for sale ticket {sale.id}")
        return record

    def _get_invoice_type(self, invoice):
        """Determine Verifactu invoice type from invoice model."""
        from .models import VerifactuRecord

        # Check invoice type attribute if it exists
        invoice_type = getattr(invoice, 'invoice_type', 'standard')

        if invoice_type == 'simplified':
            return VerifactuRecord.InvoiceType.F2
        elif invoice_type == 'rectifying':
            return VerifactuRecord.InvoiceType.R1
        else:
            return VerifactuRecord.InvoiceType.F1

    # =========================================================================
    # Hook Callbacks Implementation
    # =========================================================================

    def _add_verifactu_hash_to_lines(self, lines, invoice=None, **kwargs):
        """
        Add Verifactu hash information to invoice lines.

        This is called by invoicing module's filter_lines hook.
        """
        from .models import VerifactuConfig as VConfig

        config = VConfig.get_config()
        if not config.enabled:
            return lines

        # Lines don't need modification for Verifactu
        # The hash is calculated on the full invoice, not per line
        return lines

    def _validate_verifactu_totals(self, totals, invoice=None, **kwargs):
        """
        Validate invoice totals meet Verifactu requirements.

        This is called by invoicing module's filter_totals hook.
        Ensures amounts have correct decimal precision.
        """
        from decimal import Decimal, ROUND_HALF_UP
        from .models import VerifactuConfig as VConfig

        config = VConfig.get_config()
        if not config.enabled:
            return totals

        # Ensure 2 decimal places for all amounts (AEAT requirement)
        if 'base_amount' in totals:
            totals['base_amount'] = Decimal(totals['base_amount']).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
        if 'tax_amount' in totals:
            totals['tax_amount'] = Decimal(totals['tax_amount']).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
        if 'total_amount' in totals:
            totals['total_amount'] = Decimal(totals['total_amount']).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )

        return totals

    # =========================================================================
    # Slot Context Functions
    # =========================================================================

    def _get_qr_context(self, context):
        """
        Get context for QR code slot in invoice footer.

        Returns Verifactu record info including QR URL.
        """
        from .models import VerifactuConfig as VConfig, VerifactuRecord

        config = VConfig.get_config()
        if not config.enabled:
            return {'verifactu_enabled': False}

        invoice = context.get('invoice')
        if not invoice:
            return {'verifactu_enabled': True, 'verifactu_record': None}

        # Find the Verifactu record for this invoice
        try:
            record = VerifactuRecord.objects.filter(
                invoice_id=invoice.id
            ).first()

            return {
                'verifactu_enabled': True,
                'verifactu_record': record,
                'qr_url': record.qr_url if record else None,
                'record_hash': record.record_hash[:16] + '...' if record else None,
                'is_verifactu_mode': config.is_verifactu_mode,
            }
        except Exception as e:
            logger.warning(f"Error getting Verifactu QR context: {e}")
            return {'verifactu_enabled': True, 'verifactu_record': None}

    def _get_badge_context(self, context):
        """
        Get context for Verifactu badge in invoice header.

        Shows whether the invoice is registered with AEAT.
        """
        from .models import VerifactuConfig as VConfig

        config = VConfig.get_config()
        return {
            'verifactu_enabled': config.enabled,
            'verifactu_mode': config.get_mode_display() if config.enabled else None,
            'show_badge': config.enabled and config.is_verifactu_mode,
        }
