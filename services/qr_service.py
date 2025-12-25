"""
QR Code Service for Verifactu
Generates QR codes according to AEAT specifications.

QR Code Format:
https://www2.agenciatributaria.gob.es/wlpl/TIKE-CONT/ValidarQR?nif=XXXXX&numserie=XXXXX&fecha=DD-MM-YYYY&importe=XXXXX
"""

import io
import base64
from urllib.parse import urlencode
from typing import Optional

try:
    import qrcode
    from qrcode.constants import ERROR_CORRECT_M
    HAS_QRCODE = True
except ImportError:
    HAS_QRCODE = False


class QRServiceError(Exception):
    """Base exception for QR service errors."""
    pass


class QRService:
    """
    Service for generating Verifactu QR codes.

    QR codes allow customers to verify invoices directly with AEAT.
    """

    # AEAT verification URL
    AEAT_QR_BASE_URL = "https://www2.agenciatributaria.gob.es/wlpl/TIKE-CONT/ValidarQR"

    # QR code settings per AEAT specifications
    QR_VERSION = 1
    QR_BOX_SIZE = 10
    QR_BORDER = 4
    QR_ERROR_CORRECTION = ERROR_CORRECT_M if HAS_QRCODE else None

    @classmethod
    def is_available(cls) -> bool:
        """Check if QR code generation is available."""
        return HAS_QRCODE

    @classmethod
    def generate_verification_url(
        cls,
        issuer_nif: str,
        invoice_number: str,
        invoice_date,  # date object
        total_amount,  # Decimal
    ) -> str:
        """
        Generate the AEAT verification URL for a QR code.

        Args:
            issuer_nif: Issuer's NIF
            invoice_number: Invoice number/series
            invoice_date: Invoice date
            total_amount: Total invoice amount

        Returns:
            Complete verification URL
        """
        # Format date as DD-MM-YYYY
        date_str = invoice_date.strftime('%d-%m-%Y')

        # Format amount with 2 decimals
        amount_str = f"{total_amount:.2f}"

        params = {
            'nif': issuer_nif,
            'numserie': invoice_number,
            'fecha': date_str,
            'importe': amount_str,
        }

        return f"{cls.AEAT_QR_BASE_URL}?{urlencode(params)}"

    @classmethod
    def generate_qr_code(
        cls,
        issuer_nif: str,
        invoice_number: str,
        invoice_date,
        total_amount,
        output_format: str = 'png',
    ) -> bytes:
        """
        Generate QR code image bytes.

        Args:
            issuer_nif: Issuer's NIF
            invoice_number: Invoice number/series
            invoice_date: Invoice date
            total_amount: Total invoice amount
            output_format: Image format ('png', 'svg')

        Returns:
            QR code image as bytes

        Raises:
            QRServiceError: If qrcode library is not available
        """
        if not HAS_QRCODE:
            raise QRServiceError(
                "QR code generation requires 'qrcode' and 'pillow' packages. "
                "Install with: pip install qrcode[pil]"
            )

        url = cls.generate_verification_url(
            issuer_nif, invoice_number, invoice_date, total_amount
        )

        qr = qrcode.QRCode(
            version=cls.QR_VERSION,
            error_correction=cls.QR_ERROR_CORRECTION,
            box_size=cls.QR_BOX_SIZE,
            border=cls.QR_BORDER,
        )
        qr.add_data(url)
        qr.make(fit=True)

        if output_format.lower() == 'svg':
            # SVG output
            import qrcode.image.svg
            factory = qrcode.image.svg.SvgImage
            img = qr.make_image(image_factory=factory)
            buffer = io.BytesIO()
            img.save(buffer)
            return buffer.getvalue()
        else:
            # PNG output (default)
            img = qr.make_image(fill_color="black", back_color="white")
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            return buffer.getvalue()

    @classmethod
    def generate_qr_code_base64(
        cls,
        issuer_nif: str,
        invoice_number: str,
        invoice_date,
        total_amount,
        output_format: str = 'png',
    ) -> str:
        """
        Generate QR code as base64 encoded string.

        Useful for embedding in HTML templates.

        Args:
            issuer_nif: Issuer's NIF
            invoice_number: Invoice number/series
            invoice_date: Invoice date
            total_amount: Total invoice amount
            output_format: Image format ('png', 'svg')

        Returns:
            Base64 encoded QR code image
        """
        qr_bytes = cls.generate_qr_code(
            issuer_nif, invoice_number, invoice_date, total_amount, output_format
        )
        return base64.b64encode(qr_bytes).decode('utf-8')

    @classmethod
    def generate_qr_data_uri(
        cls,
        issuer_nif: str,
        invoice_number: str,
        invoice_date,
        total_amount,
    ) -> str:
        """
        Generate QR code as a data URI for direct HTML embedding.

        Example: <img src="data:image/png;base64,..." />

        Args:
            issuer_nif: Issuer's NIF
            invoice_number: Invoice number/series
            invoice_date: Invoice date
            total_amount: Total invoice amount

        Returns:
            Data URI string
        """
        qr_base64 = cls.generate_qr_code_base64(
            issuer_nif, invoice_number, invoice_date, total_amount, 'png'
        )
        return f"data:image/png;base64,{qr_base64}"

    @classmethod
    def generate_for_record(cls, record) -> Optional[str]:
        """
        Generate QR code data URI for a VerifactuRecord.

        Args:
            record: VerifactuRecord instance

        Returns:
            Data URI string or None if QR not available
        """
        if not cls.is_available():
            return None

        try:
            return cls.generate_qr_data_uri(
                issuer_nif=record.issuer_nif,
                invoice_number=record.invoice_number,
                invoice_date=record.invoice_date,
                total_amount=record.total_amount,
            )
        except Exception:
            return None
