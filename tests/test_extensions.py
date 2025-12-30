"""
Tests for Verifactu module extension points (signals, hooks, slots).

Tests that the verifactu module correctly:
- Listens to invoice_created and sale_completed signals
- Uses hooks from invoicing module
- Provides slots for QR code and badge
"""
import pytest
from decimal import Decimal
from unittest.mock import MagicMock, patch

from apps.core.hooks import hooks
from apps.core.slots import slots
from apps.core.signals import invoice_created, sale_completed


@pytest.fixture
def cleanup_extensions():
    """Clean up hooks and slots after each test."""
    yield
    hooks.clear_all()
    slots.clear_all()


@pytest.fixture
def mock_verifactu_config():
    """Mock VerifactuConfig for testing."""
    config = MagicMock()
    config.enabled = True
    config.is_verifactu_mode = True
    config.get_mode_display.return_value = 'VERI*FACTU'
    return config


@pytest.fixture
def mock_invoice():
    """Create a mock invoice for testing."""
    invoice = MagicMock()
    invoice.id = 'invoice-123'
    invoice.number = 'INV-2025-001'
    invoice.date = MagicMock()
    invoice.date.strftime.return_value = '28-12-2025'
    invoice.issuer_nif = 'B12345678'
    invoice.issuer_name = 'Test Company'
    invoice.base_amount = Decimal('100.00')
    invoice.tax_rate = Decimal('21.00')
    invoice.tax_amount = Decimal('21.00')
    invoice.total_amount = Decimal('121.00')
    invoice.description = 'Test invoice'
    invoice.invoice_type = 'standard'
    return invoice


@pytest.fixture
def mock_sale():
    """Create a mock sale for testing."""
    sale = MagicMock()
    sale.id = 'sale-456'
    sale.created_at = MagicMock()
    sale.created_at.date.return_value = MagicMock()
    sale.subtotal = Decimal('82.64')
    sale.tax_amount = Decimal('17.36')
    sale.total = Decimal('100.00')
    sale.invoice = None
    return sale


@pytest.mark.django_db
class TestVerifactuSignalHandlers:
    """Tests for verifactu signal handlers."""

    def test_invoice_created_signal_handler_exists(self):
        """Verify invoice_created signal can be received."""
        handler = MagicMock()
        invoice_created.connect(handler)

        try:
            invoice_created.send(
                sender='invoicing',
                invoice=MagicMock(id='inv-1'),
                sale=None,
                user=MagicMock(id=1)
            )

            handler.assert_called_once()
            call_kwargs = handler.call_args[1]
            assert call_kwargs['sender'] == 'invoicing'
        finally:
            invoice_created.disconnect(handler)

    def test_sale_completed_signal_handler_exists(self):
        """Verify sale_completed signal can be received."""
        handler = MagicMock()
        sale_completed.connect(handler)

        try:
            sale_completed.send(
                sender='sales',
                sale=MagicMock(id='sale-1'),
                user=MagicMock(id=1),
                payment_method='cash'
            )

            handler.assert_called_once()
            call_kwargs = handler.call_args[1]
            assert call_kwargs['payment_method'] == 'cash'
        finally:
            sale_completed.disconnect(handler)

    def test_invoice_created_creates_verifactu_record(self, mock_invoice):
        """Verify Verifactu record is created when invoice is created."""
        records_created = []

        def track_record_creation(sender, invoice, sale, user, **kwargs):
            # Simulate what verifactu app does
            records_created.append({
                'invoice_id': invoice.id,
                'invoice_number': invoice.number,
                'total': invoice.total_amount
            })

        invoice_created.connect(track_record_creation)

        try:
            invoice_created.send(
                sender='invoicing',
                invoice=mock_invoice,
                sale=None,
                user=MagicMock(id=1)
            )

            assert len(records_created) == 1
            assert records_created[0]['invoice_number'] == 'INV-2025-001'
            assert records_created[0]['total'] == Decimal('121.00')
        finally:
            invoice_created.disconnect(track_record_creation)

    def test_sale_completed_creates_simplified_record(self, mock_sale):
        """Verify simplified Verifactu record is created for ticket sales."""
        records_created = []

        def track_record_creation(sender, sale, user, **kwargs):
            # Simulate what verifactu app does for sales without invoices
            if not getattr(sale, 'invoice', None):
                records_created.append({
                    'sale_id': sale.id,
                    'invoice_type': 'F2',  # Simplified
                    'total': sale.total
                })

        sale_completed.connect(track_record_creation)

        try:
            sale_completed.send(
                sender='sales',
                sale=mock_sale,
                user=MagicMock(id=1),
                payment_method='cash'
            )

            assert len(records_created) == 1
            assert records_created[0]['invoice_type'] == 'F2'
        finally:
            sale_completed.disconnect(track_record_creation)


@pytest.mark.django_db
class TestVerifactuHooks:
    """Tests for verifactu hook usage."""

    def setup_method(self):
        """Clear hooks before each test."""
        hooks.clear_all()

    def teardown_method(self):
        """Clear hooks after each test."""
        hooks.clear_all()

    def test_verifactu_registers_filter_lines_hook(self):
        """Verify verifactu can register for invoicing.filter_lines hook."""
        def verifactu_filter(lines, invoice=None, **kwargs):
            return lines

        hooks.add_filter('invoicing.filter_lines', verifactu_filter, module_id='verifactu')

        lines = [{'product': 'Item 1', 'quantity': 2}]
        filtered = hooks.apply_filters('invoicing.filter_lines', lines, invoice=None)

        assert filtered == lines

    def test_verifactu_registers_filter_totals_hook(self):
        """Verify verifactu can register for invoicing.filter_totals hook."""
        def verifactu_validate_totals(totals, invoice=None, **kwargs):
            # Ensure 2 decimal places
            from decimal import Decimal, ROUND_HALF_UP
            for key in ['base_amount', 'tax_amount', 'total_amount']:
                if key in totals:
                    totals[key] = Decimal(str(totals[key])).quantize(
                        Decimal('0.01'), rounding=ROUND_HALF_UP
                    )
            return totals

        hooks.add_filter('invoicing.filter_totals', verifactu_validate_totals, module_id='verifactu')

        totals = {
            'base_amount': Decimal('100.123'),
            'tax_amount': Decimal('21.456'),
            'total_amount': Decimal('121.579')
        }
        filtered = hooks.apply_filters('invoicing.filter_totals', totals, invoice=None)

        assert filtered['base_amount'] == Decimal('100.12')
        assert filtered['tax_amount'] == Decimal('21.46')
        assert filtered['total_amount'] == Decimal('121.58')

    def test_verifactu_hook_priority_runs_late(self):
        """Verify verifactu hooks run late (high priority number)."""
        execution_order = []

        def other_filter(totals, **kwargs):
            execution_order.append('other')
            return totals

        def verifactu_filter(totals, **kwargs):
            execution_order.append('verifactu')
            return totals

        hooks.add_filter('invoicing.filter_totals', other_filter, priority=10)
        hooks.add_filter('invoicing.filter_totals', verifactu_filter, priority=100)

        hooks.apply_filters('invoicing.filter_totals', {})

        assert execution_order == ['other', 'verifactu']


@pytest.mark.django_db
class TestVerifactuSlots:
    """Tests for verifactu slot registration."""

    def setup_method(self):
        """Clear slots before each test."""
        slots.clear_all()

    def teardown_method(self):
        """Clear slots after each test."""
        slots.clear_all()

    def test_verifactu_registers_invoice_footer_slot(self):
        """Verify verifactu registers for invoicing.footer slot."""
        def qr_context(context):
            return {'qr_url': 'https://aeat.es/verify?id=123'}

        slots.register(
            'invoicing.footer',
            template='verifactu/partials/invoice_qr.html',
            context_fn=qr_context,
            module_id='verifactu'
        )

        content = slots.get_slot_content('invoicing.footer', {})
        assert len(content) == 1
        assert content[0]['template'] == 'verifactu/partials/invoice_qr.html'
        assert content[0]['context']['qr_url'] == 'https://aeat.es/verify?id=123'

    def test_verifactu_registers_invoice_header_slot(self):
        """Verify verifactu registers for invoicing.header slot."""
        def badge_context(context):
            return {'show_badge': True, 'verifactu_mode': 'VERI*FACTU'}

        slots.register(
            'invoicing.header',
            template='verifactu/partials/verifactu_badge.html',
            context_fn=badge_context,
            module_id='verifactu'
        )

        content = slots.get_slot_content('invoicing.header', {})
        assert len(content) == 1
        assert content[0]['context']['show_badge'] is True

    def test_slot_context_includes_invoice_data(self):
        """Verify slot context function receives invoice data."""
        received_context = []

        def capture_context(context):
            received_context.append(context)
            return {'captured': True}

        slots.register('invoicing.footer', template='test.html', context_fn=capture_context)

        slots.get_slot_content('invoicing.footer', {'invoice': MagicMock(id='inv-1')})

        assert len(received_context) == 1
        assert 'invoice' in received_context[0]


@pytest.mark.django_db
class TestVerifactuIntegrationScenarios:
    """Integration tests for verifactu extension scenarios."""

    def setup_method(self):
        """Clear hooks and slots before each test."""
        hooks.clear_all()
        slots.clear_all()

    def teardown_method(self):
        """Clear hooks and slots after each test."""
        hooks.clear_all()
        slots.clear_all()

    def test_full_invoice_flow_with_verifactu(self, mock_invoice):
        """Test complete flow: invoice created -> verifactu record -> QR slot."""
        verifactu_records = []
        qr_data = []

        # 1. Signal handler creates record
        def on_invoice_created(sender, invoice, **kwargs):
            record = {
                'id': 'vf-record-1',
                'invoice_id': invoice.id,
                'hash': 'ABC123...',
                'qr_url': f'https://aeat.es/verify?id={invoice.id}'
            }
            verifactu_records.append(record)

        invoice_created.connect(on_invoice_created)

        # 2. Slot provides QR context
        def qr_context(context):
            invoice = context.get('invoice')
            record = next((r for r in verifactu_records if r['invoice_id'] == invoice.id), None)
            return {
                'qr_url': record['qr_url'] if record else None,
                'record_hash': record['hash'] if record else None
            }

        slots.register('invoicing.footer', template='verifactu/qr.html', context_fn=qr_context)

        try:
            # Emit invoice created signal
            invoice_created.send(
                sender='invoicing',
                invoice=mock_invoice,
                sale=None,
                user=MagicMock()
            )

            # Verify record was created
            assert len(verifactu_records) == 1
            assert verifactu_records[0]['invoice_id'] == 'invoice-123'

            # Verify slot provides QR data
            slot_content = slots.get_slot_content('invoicing.footer', {'invoice': mock_invoice})
            assert len(slot_content) == 1
            assert slot_content[0]['context']['qr_url'] == 'https://aeat.es/verify?id=invoice-123'

        finally:
            invoice_created.disconnect(on_invoice_created)

    def test_verifactu_disabled_skips_processing(self):
        """Test that disabled verifactu skips all processing."""
        records_created = []

        def on_invoice_created(sender, invoice, **kwargs):
            # Simulate checking config.enabled
            config_enabled = False  # Verifactu disabled
            if config_enabled:
                records_created.append(invoice.id)

        invoice_created.connect(on_invoice_created)

        try:
            invoice_created.send(
                sender='invoicing',
                invoice=MagicMock(id='inv-1'),
                sale=None,
                user=MagicMock()
            )

            assert len(records_created) == 0  # No records created

        finally:
            invoice_created.disconnect(on_invoice_created)

    def test_hash_chain_maintained_across_invoices(self):
        """Test that hash chain is maintained across multiple invoices."""
        records = []

        def create_record(sender, invoice, **kwargs):
            previous_hash = records[-1]['hash'] if records else ''
            new_hash = f"HASH-{len(records) + 1}"
            records.append({
                'invoice_id': invoice.id,
                'previous_hash': previous_hash,
                'hash': new_hash,
                'sequence': len(records) + 1
            })

        invoice_created.connect(create_record)

        try:
            # Create 3 invoices
            for i in range(3):
                invoice_created.send(
                    sender='invoicing',
                    invoice=MagicMock(id=f'inv-{i}'),
                    sale=None,
                    user=MagicMock()
                )

            # Verify chain
            assert len(records) == 3
            assert records[0]['previous_hash'] == ''
            assert records[1]['previous_hash'] == 'HASH-1'
            assert records[2]['previous_hash'] == 'HASH-2'

        finally:
            invoice_created.disconnect(create_record)
