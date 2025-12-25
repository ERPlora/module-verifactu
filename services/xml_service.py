"""
XML Service for Verifactu
Generates XML records according to AEAT XSD specifications.

Reference: SuministroInformacion.xsd, SuministroLR.xsd
"""

import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime
from typing import Optional
from django.utils import timezone


class XMLServiceError(Exception):
    """Base exception for XML service errors."""
    pass


class XMLValidationError(XMLServiceError):
    """Raised when XML validation fails."""
    pass


class XMLService:
    """
    Service for generating Verifactu XML documents.

    All XML is generated in UTF-8 encoding and must pass AEAT XSD validation.
    """

    # Namespaces
    NAMESPACES = {
        'soapenv': 'http://schemas.xmlsoap.org/soap/envelope/',
        'sf': 'https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/SuministroInformacion.xsd',
    }

    @classmethod
    def create_envelope(cls) -> ET.Element:
        """Create SOAP envelope with namespaces."""
        envelope = ET.Element('soapenv:Envelope')
        for prefix, uri in cls.NAMESPACES.items():
            envelope.set(f'xmlns:{prefix}', uri)
        return envelope

    @classmethod
    def format_timestamp(cls, dt: datetime) -> str:
        """Format datetime for XML."""
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt)
        iso_str = dt.strftime('%Y-%m-%dT%H:%M:%S%z')
        if len(iso_str) > 5 and iso_str[-3] != ':':
            iso_str = iso_str[:-2] + ':' + iso_str[-2:]
        return iso_str

    @classmethod
    def format_date(cls, date) -> str:
        """Format date for XML (DD-MM-YYYY)."""
        return date.strftime('%d-%m-%Y')

    @classmethod
    def format_amount(cls, amount) -> str:
        """Format decimal amount for XML."""
        return f"{amount:.2f}"

    @classmethod
    def generate_alta_xml(cls, record, config) -> str:
        """
        Generate XML for an Alta (registration) record.

        Args:
            record: VerifactuRecord instance
            config: VerifactuConfig instance

        Returns:
            XML string in UTF-8 encoding
        """
        envelope = cls.create_envelope()

        # Header
        header = ET.SubElement(envelope, 'soapenv:Header')

        # Body
        body = ET.SubElement(envelope, 'soapenv:Body')
        reg_factu = ET.SubElement(body, 'sf:RegFactuSistemaFacturacion')

        # Cabecera (Header info)
        cabecera = ET.SubElement(reg_factu, 'sf:Cabecera')
        obligado = ET.SubElement(cabecera, 'sf:ObligadoEmision')
        ET.SubElement(obligado, 'sf:NombreRazon').text = record.issuer_name
        ET.SubElement(obligado, 'sf:NIF').text = record.issuer_nif

        # RegistroFactura
        registro = ET.SubElement(reg_factu, 'sf:RegistroFactura')
        alta = ET.SubElement(registro, 'sf:RegistroAlta')

        # IDFactura
        id_factura = ET.SubElement(alta, 'sf:IDFactura')
        ET.SubElement(id_factura, 'sf:IDEmisorFactura').text = record.issuer_nif
        ET.SubElement(id_factura, 'sf:NumSerieFactura').text = record.invoice_number
        ET.SubElement(id_factura, 'sf:FechaExpedicionFactura').text = cls.format_date(record.invoice_date)

        # Invoice details
        ET.SubElement(alta, 'sf:TipoFactura').text = record.invoice_type
        ET.SubElement(alta, 'sf:DescripcionOperacion').text = record.description or 'Factura'

        # Amounts
        ET.SubElement(alta, 'sf:ImporteTotal').text = cls.format_amount(record.total_amount)

        # Desglose IVA (Tax breakdown)
        desglose = ET.SubElement(alta, 'sf:Desglose')
        detalle_desglose = ET.SubElement(desglose, 'sf:DetalleDesglose')
        ET.SubElement(detalle_desglose, 'sf:Impuesto').text = '01'  # IVA
        ET.SubElement(detalle_desglose, 'sf:ClaveRegimen').text = '01'  # General
        ET.SubElement(detalle_desglose, 'sf:TipoImpositivo').text = cls.format_amount(record.tax_rate)
        ET.SubElement(detalle_desglose, 'sf:BaseImponible').text = cls.format_amount(record.base_amount)
        ET.SubElement(detalle_desglose, 'sf:CuotaRepercutida').text = cls.format_amount(record.tax_amount)

        # Cuota Total
        ET.SubElement(alta, 'sf:CuotaTotal').text = cls.format_amount(record.tax_amount)

        # Encadenamiento (Hash chain)
        encadenamiento = ET.SubElement(alta, 'sf:Encadenamiento')
        if record.is_first_record:
            ET.SubElement(encadenamiento, 'sf:PrimerRegistro').text = 'S'
        else:
            ET.SubElement(encadenamiento, 'sf:PrimerRegistro').text = 'N'
            reg_anterior = ET.SubElement(encadenamiento, 'sf:RegistroAnterior')
            ET.SubElement(reg_anterior, 'sf:Huella').text = record.previous_hash

        # Sistema Informatico (Software info)
        sistema = ET.SubElement(alta, 'sf:SistemaInformatico')
        ET.SubElement(sistema, 'sf:NombreRazon').text = config.software_name
        ET.SubElement(sistema, 'sf:NIF').text = config.software_nif or 'B00000000'
        ET.SubElement(sistema, 'sf:NombreSistemaInformatico').text = config.software_name
        ET.SubElement(sistema, 'sf:IdSistemaInformatico').text = config.software_id
        ET.SubElement(sistema, 'sf:Version').text = config.software_version
        ET.SubElement(sistema, 'sf:NumeroInstalacion').text = '1'

        # Timestamp and Hash
        ET.SubElement(alta, 'sf:FechaHoraHusoGenRegistro').text = cls.format_timestamp(record.generation_timestamp)
        ET.SubElement(alta, 'sf:Huella').text = record.record_hash

        # Generate pretty XML
        xml_str = ET.tostring(envelope, encoding='unicode')
        return cls.prettify_xml(xml_str)

    @classmethod
    def generate_anulacion_xml(cls, record, config) -> str:
        """
        Generate XML for an Anulación (cancellation) record.

        Args:
            record: VerifactuRecord instance
            config: VerifactuConfig instance

        Returns:
            XML string in UTF-8 encoding
        """
        envelope = cls.create_envelope()

        header = ET.SubElement(envelope, 'soapenv:Header')
        body = ET.SubElement(envelope, 'soapenv:Body')
        reg_factu = ET.SubElement(body, 'sf:RegFactuSistemaFacturacion')

        # Cabecera
        cabecera = ET.SubElement(reg_factu, 'sf:Cabecera')
        obligado = ET.SubElement(cabecera, 'sf:ObligadoEmision')
        ET.SubElement(obligado, 'sf:NombreRazon').text = record.issuer_name
        ET.SubElement(obligado, 'sf:NIF').text = record.issuer_nif

        # RegistroFactura
        registro = ET.SubElement(reg_factu, 'sf:RegistroFactura')
        anulacion = ET.SubElement(registro, 'sf:RegistroAnulacion')

        # IDFactura
        id_factura = ET.SubElement(anulacion, 'sf:IDFactura')
        ET.SubElement(id_factura, 'sf:IDEmisorFactura').text = record.issuer_nif
        ET.SubElement(id_factura, 'sf:NumSerieFactura').text = record.invoice_number
        ET.SubElement(id_factura, 'sf:FechaExpedicionFactura').text = cls.format_date(record.invoice_date)

        # Encadenamiento
        encadenamiento = ET.SubElement(anulacion, 'sf:Encadenamiento')
        ET.SubElement(encadenamiento, 'sf:PrimerRegistro').text = 'N'
        reg_anterior = ET.SubElement(encadenamiento, 'sf:RegistroAnterior')
        ET.SubElement(reg_anterior, 'sf:Huella').text = record.previous_hash

        # Sistema Informatico
        sistema = ET.SubElement(anulacion, 'sf:SistemaInformatico')
        ET.SubElement(sistema, 'sf:NombreRazon').text = config.software_name
        ET.SubElement(sistema, 'sf:NIF').text = config.software_nif or 'B00000000'
        ET.SubElement(sistema, 'sf:NombreSistemaInformatico').text = config.software_name
        ET.SubElement(sistema, 'sf:IdSistemaInformatico').text = config.software_id
        ET.SubElement(sistema, 'sf:Version').text = config.software_version

        # Timestamp and Hash
        ET.SubElement(anulacion, 'sf:FechaHoraHusoGenRegistro').text = cls.format_timestamp(record.generation_timestamp)
        ET.SubElement(anulacion, 'sf:Huella').text = record.record_hash

        xml_str = ET.tostring(envelope, encoding='unicode')
        return cls.prettify_xml(xml_str)

    @classmethod
    def prettify_xml(cls, xml_string: str) -> str:
        """
        Format XML with proper indentation.

        Args:
            xml_string: Raw XML string

        Returns:
            Formatted XML string
        """
        dom = minidom.parseString(xml_string)
        return dom.toprettyxml(indent='  ', encoding='UTF-8').decode('utf-8')

    @classmethod
    def generate_record_xml(cls, record, config) -> str:
        """
        Generate XML for a record based on its type.

        Args:
            record: VerifactuRecord instance
            config: VerifactuConfig instance

        Returns:
            XML string
        """
        if record.record_type == 'alta':
            return cls.generate_alta_xml(record, config)
        else:
            return cls.generate_anulacion_xml(record, config)

    @classmethod
    def validate_xml(cls, xml_string: str) -> tuple[bool, Optional[str]]:
        """
        Validate XML structure (basic validation).

        For full XSD validation, use an external library like lxml.

        Args:
            xml_string: XML string to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            ET.fromstring(xml_string.encode('utf-8') if isinstance(xml_string, str) else xml_string)
            return True, None
        except ET.ParseError as e:
            return False, str(e)

    @classmethod
    def extract_response_data(cls, response_xml: str) -> dict:
        """
        Extract relevant data from AEAT response XML.

        Args:
            response_xml: AEAT response XML string

        Returns:
            Dictionary with response data
        """
        try:
            root = ET.fromstring(response_xml)

            # Extract common fields (adjust namespaces as needed)
            result = {
                'success': False,
                'code': '',
                'message': '',
                'csv': '',
            }

            # Parse response structure (simplified)
            # Real implementation needs proper namespace handling

            return result
        except Exception as e:
            return {
                'success': False,
                'code': 'PARSE_ERROR',
                'message': str(e),
                'csv': '',
            }
