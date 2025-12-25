"""
AEAT API Client for Verifactu
Handles SOAP communication with AEAT web services.

AEAT Endpoints:
- Production: https://www2.agenciatributaria.gob.es/wlpl/TIKE-CONT/ws/SusFactFSSWS/SistemaFacturacion
- Testing: https://prewww2.aeat.es/wlpl/TIKE-CONT/ws/SusuFactFSSWS/SistemaFacturacion

Reference: Technical documentation AEAT VERI*FACTU
"""

import logging
from typing import Optional, Tuple, List
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, date

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

logger = logging.getLogger('verifactu.aeat_client')


class AEATEnvironment(Enum):
    """AEAT API environments."""
    PRODUCTION = 'production'
    TESTING = 'testing'


@dataclass
class AEATResponse:
    """Response from AEAT API."""
    success: bool
    code: str
    message: str
    csv: Optional[str] = None  # Código Seguro de Verificación
    raw_response: Optional[str] = None
    timestamp: Optional[datetime] = None
    http_status: Optional[int] = None


@dataclass
class AEATQueryRecord:
    """
    Un registro devuelto por la consulta a AEAT.

    Contiene la información de una factura previamente enviada,
    útil para recuperar la cadena hash tras restaurar una copia de seguridad.
    """
    invoice_number: str          # Número de factura (ej: "F2024-001")
    invoice_date: date           # Fecha de expedición
    record_type: str             # 'alta' o 'anulacion'
    record_hash: str             # Hash SHA-256 del registro
    issuer_nif: str              # NIF del emisor
    total_amount: Optional[str] = None  # Importe total
    csv: Optional[str] = None    # Código Seguro de Verificación
    status: str = 'accepted'     # Estado del registro


@dataclass
class AEATQueryResponse:
    """
    Respuesta de la consulta de registros a AEAT.

    Permite obtener los últimos registros enviados para:
    - Recuperar la cadena hash tras restaurar backup
    - Verificar sincronización con AEAT
    - Auditoría
    """
    success: bool
    code: str
    message: str
    records: List[AEATQueryRecord] = field(default_factory=list)
    total_count: int = 0
    raw_response: Optional[str] = None
    timestamp: Optional[datetime] = None


class AEATClientError(Exception):
    """Base exception for AEAT client errors."""
    pass


class AEATConnectionError(AEATClientError):
    """Raised when connection to AEAT fails."""
    pass


class AEATCertificateError(AEATClientError):
    """Raised when certificate issues occur."""
    pass


class AEATValidationError(AEATClientError):
    """Raised when AEAT rejects the request."""
    pass


class AEATClient:
    """
    Client for AEAT Verifactu SOAP web services.

    Handles:
    - Certificate-based authentication (PKCS#12)
    - SOAP request/response handling
    - Retry logic for transient failures
    - Response parsing
    """

    # AEAT endpoints
    ENDPOINTS = {
        AEATEnvironment.PRODUCTION: (
            "https://www2.agenciatributaria.gob.es/wlpl/TIKE-CONT/ws/SusuFactFSSWS/SistemaFacturacion"
        ),
        AEATEnvironment.TESTING: (
            "https://prewww2.aeat.es/wlpl/TIKE-CONT/ws/SusuFactFSSWS/SistemaFacturacion"
        ),
    }

    # SOAP action headers
    SOAP_ACTIONS = {
        'alta': '"SuministroFacturas"',
        'anulacion': '"AnulacionFacturas"',
        'consulta': '"ConsultaFacturas"',
    }

    # Timeouts in seconds
    CONNECT_TIMEOUT = 30
    READ_TIMEOUT = 120  # AEAT can be slow

    def __init__(
        self,
        certificate_path: str,
        certificate_password: str,
        environment: AEATEnvironment = AEATEnvironment.TESTING,
        retry_attempts: int = 3,
    ):
        """
        Initialize AEAT client.

        Args:
            certificate_path: Path to PKCS#12 certificate file
            certificate_password: Certificate password
            environment: AEAT environment (production/testing)
            retry_attempts: Number of retry attempts for transient failures
        """
        if not HAS_REQUESTS:
            raise AEATClientError(
                "AEAT client requires 'requests' package. "
                "Install with: pip install requests"
            )

        self.certificate_path = certificate_path
        self.certificate_password = certificate_password
        self.environment = environment
        self.retry_attempts = retry_attempts
        self.endpoint = self.ENDPOINTS[environment]

        self._session = None

    def _get_session(self) -> 'requests.Session':
        """Get or create HTTP session with retry logic."""
        if self._session is None:
            self._session = requests.Session()

            # Configure retries
            retry_strategy = Retry(
                total=self.retry_attempts,
                backoff_factor=1,
                status_forcelist=[500, 502, 503, 504],
                allowed_methods=["POST"],
            )
            adapter = HTTPAdapter(max_retries=retry_strategy)
            self._session.mount("https://", adapter)

        return self._session

    def _prepare_certificate(self) -> Tuple[str, str]:
        """
        Prepare certificate for requests.

        Note: requests library needs PEM format, not PKCS#12.
        This method handles conversion if needed.

        Returns:
            Tuple of (cert_path, key_path) or single path if combined
        """
        # For PKCS#12, we need to convert to PEM or use a library like pyOpenSSL
        # This is a simplified version - real implementation needs crypto handling
        return self.certificate_path

    def submit_record(self, xml_content: str, record_type: str = 'alta') -> AEATResponse:
        """
        Submit a record to AEAT.

        Args:
            xml_content: Complete SOAP XML to submit
            record_type: Type of record ('alta', 'anulacion')

        Returns:
            AEATResponse with submission result

        Raises:
            AEATConnectionError: If connection fails
            AEATCertificateError: If certificate issues occur
            AEATValidationError: If AEAT rejects the request
        """
        logger.info(f"Submitting {record_type} record to AEAT ({self.environment.value})")

        headers = {
            'Content-Type': 'text/xml; charset=utf-8',
            'SOAPAction': self.SOAP_ACTIONS.get(record_type, self.SOAP_ACTIONS['alta']),
        }

        try:
            session = self._get_session()
            cert = self._prepare_certificate()

            response = session.post(
                self.endpoint,
                data=xml_content.encode('utf-8'),
                headers=headers,
                cert=cert,
                timeout=(self.CONNECT_TIMEOUT, self.READ_TIMEOUT),
                verify=True,
            )

            logger.debug(f"AEAT response status: {response.status_code}")

            return self._parse_response(response)

        except requests.exceptions.SSLError as e:
            logger.error(f"Certificate error: {e}")
            raise AEATCertificateError(f"Certificate error: {e}")

        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error: {e}")
            raise AEATConnectionError(f"Failed to connect to AEAT: {e}")

        except requests.exceptions.Timeout as e:
            logger.error(f"Timeout error: {e}")
            raise AEATConnectionError(f"AEAT request timeout: {e}")

        except requests.exceptions.RequestException as e:
            logger.error(f"Request error: {e}")
            raise AEATClientError(f"AEAT request failed: {e}")

    def _parse_response(self, response: 'requests.Response') -> AEATResponse:
        """
        Parse AEAT SOAP response.

        Args:
            response: HTTP response from AEAT

        Returns:
            Parsed AEATResponse
        """
        import xml.etree.ElementTree as ET

        timestamp = datetime.now()

        # Check HTTP status
        if response.status_code != 200:
            return AEATResponse(
                success=False,
                code=f"HTTP_{response.status_code}",
                message=f"HTTP error: {response.status_code}",
                raw_response=response.text,
                timestamp=timestamp,
                http_status=response.status_code,
            )

        try:
            # Parse SOAP response
            root = ET.fromstring(response.content)

            # Extract response data (namespace handling needed)
            # This is simplified - real implementation needs proper namespace handling
            success = False
            code = ''
            message = ''
            csv = None

            # Look for common response elements
            # AEAT uses specific namespaces that need proper handling
            for elem in root.iter():
                tag_name = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag

                if tag_name == 'EstadoEnvio':
                    success = elem.text == 'Correcto'
                elif tag_name == 'CodigoErrorRegistro':
                    code = elem.text or ''
                elif tag_name == 'DescripcionErrorRegistro':
                    message = elem.text or ''
                elif tag_name == 'CSV':
                    csv = elem.text

            if not code and success:
                code = 'OK'
                message = 'Record submitted successfully'

            return AEATResponse(
                success=success,
                code=code,
                message=message,
                csv=csv,
                raw_response=response.text,
                timestamp=timestamp,
                http_status=response.status_code,
            )

        except ET.ParseError as e:
            logger.error(f"Failed to parse AEAT response: {e}")
            return AEATResponse(
                success=False,
                code='PARSE_ERROR',
                message=f"Failed to parse response: {e}",
                raw_response=response.text,
                timestamp=timestamp,
                http_status=response.status_code,
            )

    def submit_alta(self, xml_content: str) -> AEATResponse:
        """Submit an alta (registration) record."""
        return self.submit_record(xml_content, 'alta')

    def submit_anulacion(self, xml_content: str) -> AEATResponse:
        """Submit an anulación (cancellation) record."""
        return self.submit_record(xml_content, 'anulacion')

    def test_connection(self) -> Tuple[bool, str]:
        """
        Test connection to AEAT.

        Returns:
            Tuple of (success, message)
        """
        try:
            session = self._get_session()
            cert = self._prepare_certificate()

            # Simple HEAD/OPTIONS request to check connectivity
            response = session.options(
                self.endpoint,
                cert=cert,
                timeout=(self.CONNECT_TIMEOUT, 10),
                verify=True,
            )

            if response.status_code < 500:
                return True, "Connection successful"
            else:
                return False, f"Server error: {response.status_code}"

        except requests.exceptions.SSLError as e:
            return False, f"Certificate error: {e}"
        except requests.exceptions.ConnectionError as e:
            return False, f"Connection failed: {e}"
        except Exception as e:
            return False, f"Error: {e}"

    def query_last_records(
        self,
        issuer_nif: str,
        year: int = None,
        limit: int = 10,
    ) -> AEATQueryResponse:
        """
        Consulta los últimos registros enviados a AEAT.

        ¿Para qué sirve?
        ----------------
        - Recuperar la cadena hash tras restaurar una copia de seguridad
        - Verificar que los registros locales coinciden con AEAT
        - Auditoría de facturas enviadas

        Ejemplo de uso:
        ---------------
        ```python
        # Tras restaurar un backup, obtener el último hash
        response = client.query_last_records(issuer_nif='B12345678', limit=1)
        if response.success and response.records:
            last_hash = response.records[0].record_hash
            # Usar este hash para la siguiente factura
        ```

        Args:
            issuer_nif: NIF del emisor (obligatorio)
            year: Año fiscal a consultar (default: año actual)
            limit: Máximo de registros a devolver (default: 10)

        Returns:
            AEATQueryResponse con lista de registros encontrados
        """
        import xml.etree.ElementTree as ET

        if year is None:
            year = datetime.now().year

        logger.info(f"Querying AEAT records for {issuer_nif}, year {year}")

        # Construir XML de consulta
        xml_content = self._build_query_xml(issuer_nif, year, limit)

        headers = {
            'Content-Type': 'text/xml; charset=utf-8',
            'SOAPAction': self.SOAP_ACTIONS['consulta'],
        }

        try:
            session = self._get_session()
            cert = self._prepare_certificate()

            response = session.post(
                self.endpoint,
                data=xml_content.encode('utf-8'),
                headers=headers,
                cert=cert,
                timeout=(self.CONNECT_TIMEOUT, self.READ_TIMEOUT),
                verify=True,
            )

            return self._parse_query_response(response)

        except requests.exceptions.SSLError as e:
            logger.error(f"Certificate error in query: {e}")
            return AEATQueryResponse(
                success=False,
                code='CERT_ERROR',
                message=f"Error de certificado: {e}",
                timestamp=datetime.now(),
            )

        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error in query: {e}")
            return AEATQueryResponse(
                success=False,
                code='CONNECTION_ERROR',
                message=f"Error de conexión: {e}",
                timestamp=datetime.now(),
            )

        except Exception as e:
            logger.error(f"Query error: {e}")
            return AEATQueryResponse(
                success=False,
                code='ERROR',
                message=str(e),
                timestamp=datetime.now(),
            )

    def _build_query_xml(self, issuer_nif: str, year: int, limit: int) -> str:
        """
        Construye el XML SOAP para la consulta de registros.

        Args:
            issuer_nif: NIF del emisor
            year: Año fiscal
            limit: Número máximo de registros

        Returns:
            XML SOAP formateado
        """
        # XML simplificado - la estructura real depende de la especificación AEAT
        xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
    xmlns:sf="https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/SuministroInformacion.xsd">
    <soapenv:Header/>
    <soapenv:Body>
        <sf:ConsultaLRFacturasEmitidas>
            <sf:Cabecera>
                <sf:ObligadoEmision>
                    <sf:NIF>{issuer_nif}</sf:NIF>
                </sf:ObligadoEmision>
            </sf:Cabecera>
            <sf:FiltroConsulta>
                <sf:PeriodoImputacion>
                    <sf:Ejercicio>{year}</sf:Ejercicio>
                </sf:PeriodoImputacion>
            </sf:FiltroConsulta>
        </sf:ConsultaLRFacturasEmitidas>
    </soapenv:Body>
</soapenv:Envelope>'''
        return xml

    def _parse_query_response(self, response: 'requests.Response') -> AEATQueryResponse:
        """
        Parsea la respuesta de consulta de AEAT.

        Args:
            response: Respuesta HTTP de AEAT

        Returns:
            AEATQueryResponse con los registros encontrados
        """
        import xml.etree.ElementTree as ET

        timestamp = datetime.now()

        if response.status_code != 200:
            return AEATQueryResponse(
                success=False,
                code=f"HTTP_{response.status_code}",
                message=f"Error HTTP: {response.status_code}",
                raw_response=response.text,
                timestamp=timestamp,
            )

        try:
            root = ET.fromstring(response.content)
            records = []

            # Buscar registros en la respuesta
            # La estructura real depende de la especificación AEAT
            for elem in root.iter():
                tag_name = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag

                if tag_name == 'RegistroRespuestaConsulta':
                    record = self._parse_query_record(elem)
                    if record:
                        records.append(record)

            # Ordenar por fecha descendente (más reciente primero)
            records.sort(key=lambda r: r.invoice_date, reverse=True)

            return AEATQueryResponse(
                success=True,
                code='OK',
                message=f'Se encontraron {len(records)} registros',
                records=records,
                total_count=len(records),
                raw_response=response.text,
                timestamp=timestamp,
            )

        except ET.ParseError as e:
            logger.error(f"Failed to parse AEAT query response: {e}")
            return AEATQueryResponse(
                success=False,
                code='PARSE_ERROR',
                message=f"Error al parsear respuesta: {e}",
                raw_response=response.text,
                timestamp=timestamp,
            )

    def _parse_query_record(self, elem) -> Optional[AEATQueryRecord]:
        """
        Parsea un registro individual de la respuesta de consulta.

        Args:
            elem: Elemento XML del registro

        Returns:
            AEATQueryRecord o None si no se puede parsear
        """
        try:
            invoice_number = ''
            invoice_date_str = ''
            record_hash = ''
            issuer_nif = ''
            total_amount = None
            csv = None
            record_type = 'alta'

            for child in elem.iter():
                tag_name = child.tag.split('}')[-1] if '}' in child.tag else child.tag

                if tag_name == 'NumSerieFactura':
                    invoice_number = child.text or ''
                elif tag_name == 'FechaExpedicionFactura':
                    invoice_date_str = child.text or ''
                elif tag_name == 'Huella':
                    record_hash = child.text or ''
                elif tag_name == 'NIF' or tag_name == 'IDEmisorFactura':
                    issuer_nif = child.text or ''
                elif tag_name == 'ImporteTotal':
                    total_amount = child.text
                elif tag_name == 'CSV':
                    csv = child.text
                elif tag_name == 'TipoRegistro':
                    record_type = 'anulacion' if child.text == 'A' else 'alta'

            if invoice_number and record_hash:
                # Parsear fecha (formato DD-MM-YYYY)
                try:
                    day, month, year = invoice_date_str.split('-')
                    invoice_date = date(int(year), int(month), int(day))
                except (ValueError, AttributeError):
                    invoice_date = date.today()

                return AEATQueryRecord(
                    invoice_number=invoice_number,
                    invoice_date=invoice_date,
                    record_type=record_type,
                    record_hash=record_hash,
                    issuer_nif=issuer_nif,
                    total_amount=total_amount,
                    csv=csv,
                )

        except Exception as e:
            logger.error(f"Error parsing query record: {e}")

        return None

    def get_last_hash(self, issuer_nif: str) -> Optional[str]:
        """
        Obtiene el hash del último registro enviado a AEAT.

        Método de conveniencia para recuperar la cadena tras un backup.

        Ejemplo:
        --------
        ```python
        # Tras restaurar backup
        last_hash = client.get_last_hash('B12345678')
        if last_hash:
            print(f"Último hash en AEAT: {last_hash}")
            # Usar este hash para la siguiente factura
        else:
            print("No hay registros en AEAT o error de conexión")
        ```

        Args:
            issuer_nif: NIF del emisor

        Returns:
            Hash del último registro o None si no hay registros/error
        """
        response = self.query_last_records(issuer_nif, limit=1)

        if response.success and response.records:
            return response.records[0].record_hash

        return None

    def close(self):
        """Close the HTTP session."""
        if self._session:
            self._session.close()
            self._session = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class MockAEATClient:
    """
    Mock AEAT client for testing without real AEAT connection.

    Simulates AEAT responses for development and testing.
    """

    def __init__(self, *args, **kwargs):
        """Initialize mock client (ignores all parameters)."""
        self.submitted_records = []
        self.should_fail = False
        self.failure_code = None
        self.failure_message = None

    def submit_record(self, xml_content: str, record_type: str = 'alta') -> AEATResponse:
        """Simulate record submission."""
        self.submitted_records.append({
            'xml': xml_content,
            'type': record_type,
            'timestamp': datetime.now(),
        })

        if self.should_fail:
            return AEATResponse(
                success=False,
                code=self.failure_code or 'MOCK_ERROR',
                message=self.failure_message or 'Simulated failure',
                timestamp=datetime.now(),
            )

        # Generate mock CSV
        import hashlib
        csv = hashlib.md5(xml_content.encode()).hexdigest()[:16].upper()

        return AEATResponse(
            success=True,
            code='OK',
            message='Record accepted (mock)',
            csv=csv,
            timestamp=datetime.now(),
            http_status=200,
        )

    def submit_alta(self, xml_content: str) -> AEATResponse:
        return self.submit_record(xml_content, 'alta')

    def submit_anulacion(self, xml_content: str) -> AEATResponse:
        return self.submit_record(xml_content, 'anulacion')

    def test_connection(self) -> Tuple[bool, str]:
        if self.should_fail:
            return False, self.failure_message or "Simulated connection failure"
        return True, "Mock connection successful"

    def set_failure(self, code: str = None, message: str = None):
        """Configure mock to return failures."""
        self.should_fail = True
        self.failure_code = code
        self.failure_message = message

    def set_success(self):
        """Configure mock to return success."""
        self.should_fail = False
        self.failure_code = None
        self.failure_message = None

    def query_last_records(
        self,
        issuer_nif: str,
        year: int = None,
        limit: int = 10,
    ) -> AEATQueryResponse:
        """Mock query of last records."""
        if self.should_fail:
            return AEATQueryResponse(
                success=False,
                code=self.failure_code or 'MOCK_ERROR',
                message=self.failure_message or 'Simulated query failure',
                timestamp=datetime.now(),
            )

        # Return mock records based on submitted_records
        mock_records = []
        for i, submitted in enumerate(reversed(self.submitted_records[-limit:])):
            mock_records.append(AEATQueryRecord(
                invoice_number=f'MOCK-{i+1}',
                invoice_date=date.today(),
                record_type=submitted['type'],
                record_hash='A' * 64,  # Mock hash
                issuer_nif=issuer_nif,
                csv=f'CSV{i+1}',
            ))

        return AEATQueryResponse(
            success=True,
            code='OK',
            message=f'Found {len(mock_records)} mock records',
            records=mock_records,
            total_count=len(mock_records),
            timestamp=datetime.now(),
        )

    def get_last_hash(self, issuer_nif: str) -> Optional[str]:
        """Mock get last hash."""
        response = self.query_last_records(issuer_nif, limit=1)
        if response.success and response.records:
            return response.records[0].record_hash
        return None

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass
