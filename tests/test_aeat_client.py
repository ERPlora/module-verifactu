"""
Integration tests for Verifactu AEAT Client.

Tests SOAP communication with AEAT web services using mock responses.
"""

import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock
from django.utils import timezone

from verifactu.services.aeat_client import (
    AEATClient,
    MockAEATClient,
    AEATResponse,
    AEATEnvironment,
    AEATClientError,
    AEATConnectionError,
    AEATCertificateError,
)


class TestMockAEATClient:
    """Tests for MockAEATClient (used in development/testing)."""

    def test_mock_client_success(self):
        """Test mock client returns success by default."""
        client = MockAEATClient()

        response = client.submit_alta('<xml>test</xml>')

        assert response.success is True
        assert response.code == 'OK'
        assert response.csv is not None

    def test_mock_client_records_submissions(self):
        """Test mock client records all submissions."""
        client = MockAEATClient()

        client.submit_alta('<xml>alta1</xml>')
        client.submit_alta('<xml>alta2</xml>')
        client.submit_anulacion('<xml>anulacion1</xml>')

        assert len(client.submitted_records) == 3
        assert client.submitted_records[0]['type'] == 'alta'
        assert client.submitted_records[2]['type'] == 'anulacion'

    def test_mock_client_configurable_failure(self):
        """Test mock client can be configured to fail."""
        client = MockAEATClient()
        client.set_failure(code='TEST_ERROR', message='Test failure message')

        response = client.submit_alta('<xml>test</xml>')

        assert response.success is False
        assert response.code == 'TEST_ERROR'
        assert response.message == 'Test failure message'

    def test_mock_client_reset_to_success(self):
        """Test mock client can be reset to success mode."""
        client = MockAEATClient()
        client.set_failure(code='ERROR', message='Error')
        client.set_success()

        response = client.submit_alta('<xml>test</xml>')

        assert response.success is True

    def test_mock_client_test_connection(self):
        """Test mock client connection test."""
        client = MockAEATClient()

        success, message = client.test_connection()

        assert success is True
        assert 'successful' in message.lower()

    def test_mock_client_test_connection_failure(self):
        """Test mock client connection test with failure."""
        client = MockAEATClient()
        client.set_failure(message='Connection refused')

        success, message = client.test_connection()

        assert success is False

    def test_mock_client_context_manager(self):
        """Test mock client works as context manager."""
        with MockAEATClient() as client:
            response = client.submit_alta('<xml>test</xml>')
            assert response.success is True


class TestAEATResponse:
    """Tests for AEATResponse dataclass."""

    def test_response_success_fields(self):
        """Test response with all success fields."""
        response = AEATResponse(
            success=True,
            code='OK',
            message='Record accepted',
            csv='ABC123DEF456',
            timestamp=datetime.now(),
            http_status=200,
        )

        assert response.success is True
        assert response.csv == 'ABC123DEF456'

    def test_response_error_fields(self):
        """Test response with error fields."""
        response = AEATResponse(
            success=False,
            code='4001',
            message='Invalid NIF format',
            raw_response='<soap:Fault>...</soap:Fault>',
        )

        assert response.success is False
        assert response.code == '4001'
        assert response.raw_response is not None


class TestAEATEnvironment:
    """Tests for AEATEnvironment enum."""

    def test_production_environment(self):
        """Test production environment value."""
        assert AEATEnvironment.PRODUCTION.value == 'production'

    def test_testing_environment(self):
        """Test testing environment value."""
        assert AEATEnvironment.TESTING.value == 'testing'


class TestAEATClient:
    """Tests for real AEATClient (mocked network calls)."""

    def test_client_initialization(self):
        """Test client initialization with parameters."""
        with patch('verifactu.services.aeat_client.HAS_REQUESTS', True):
            client = AEATClient(
                certificate_path='/path/to/cert.p12',
                certificate_password='secret',
                environment=AEATEnvironment.TESTING,
            )

            assert client.certificate_path == '/path/to/cert.p12'
            assert client.environment == AEATEnvironment.TESTING

    def test_client_endpoints(self):
        """Test client uses correct endpoints per environment."""
        assert 'prewww2.aeat.es' in AEATClient.ENDPOINTS[AEATEnvironment.TESTING]
        assert 'www2.agenciatributaria.gob.es' in AEATClient.ENDPOINTS[AEATEnvironment.PRODUCTION]

    def test_client_soap_actions(self):
        """Test SOAP actions are defined."""
        assert 'alta' in AEATClient.SOAP_ACTIONS
        assert 'anulacion' in AEATClient.SOAP_ACTIONS
        assert 'consulta' in AEATClient.SOAP_ACTIONS

    @patch('verifactu.services.aeat_client.requests')
    def test_client_submit_record_success(self, mock_requests):
        """Test successful record submission."""
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'''<?xml version="1.0"?>
            <soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
                <soap:Body>
                    <EstadoEnvio>Correcto</EstadoEnvio>
                    <CSV>TESTCSV123456</CSV>
                </soap:Body>
            </soap:Envelope>'''
        mock_response.text = mock_response.content.decode()

        mock_session = MagicMock()
        mock_session.post.return_value = mock_response
        mock_requests.Session.return_value = mock_session

        with patch('verifactu.services.aeat_client.HAS_REQUESTS', True):
            client = AEATClient(
                certificate_path='/path/to/cert.p12',
                certificate_password='secret',
            )
            client._session = mock_session

            response = client.submit_alta('<xml>test</xml>')

            assert response.http_status == 200
            mock_session.post.assert_called_once()

    @patch('verifactu.services.aeat_client.requests')
    def test_client_submit_record_http_error(self, mock_requests):
        """Test handling of HTTP error responses."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = 'Internal Server Error'

        mock_session = MagicMock()
        mock_session.post.return_value = mock_response
        mock_requests.Session.return_value = mock_session

        with patch('verifactu.services.aeat_client.HAS_REQUESTS', True):
            client = AEATClient(
                certificate_path='/path/to/cert.p12',
                certificate_password='secret',
            )
            client._session = mock_session

            response = client.submit_alta('<xml>test</xml>')

            assert response.success is False
            assert response.code == 'HTTP_500'

    @patch('verifactu.services.aeat_client.requests')
    def test_client_connection_error(self, mock_requests):
        """Test handling of connection errors."""
        mock_session = MagicMock()
        mock_session.post.side_effect = mock_requests.exceptions.ConnectionError('Network unreachable')
        mock_requests.Session.return_value = mock_session
        mock_requests.exceptions.ConnectionError = Exception
        mock_requests.exceptions.SSLError = Exception
        mock_requests.exceptions.Timeout = Exception
        mock_requests.exceptions.RequestException = Exception

        with patch('verifactu.services.aeat_client.HAS_REQUESTS', True):
            client = AEATClient(
                certificate_path='/path/to/cert.p12',
                certificate_password='secret',
            )
            client._session = mock_session

            with pytest.raises(AEATConnectionError):
                client.submit_alta('<xml>test</xml>')

    def test_client_context_manager(self):
        """Test client works as context manager."""
        with patch('verifactu.services.aeat_client.HAS_REQUESTS', True):
            with AEATClient(
                certificate_path='/path/to/cert.p12',
                certificate_password='secret',
            ) as client:
                assert client is not None


class TestAEATClientExceptions:
    """Tests for AEAT client exceptions."""

    def test_client_error_base(self):
        """Test base exception."""
        error = AEATClientError("Test error")
        assert str(error) == "Test error"

    def test_connection_error(self):
        """Test connection error."""
        error = AEATConnectionError("Connection failed")
        assert isinstance(error, AEATClientError)

    def test_certificate_error(self):
        """Test certificate error."""
        error = AEATCertificateError("Invalid certificate")
        assert isinstance(error, AEATClientError)


class TestAEATClientRetry:
    """Tests for AEAT client retry logic."""

    def test_retry_intervals(self):
        """Test retry intervals are configured."""
        from verifactu.services.aeat_client import AEATClient

        # Should have multiple retry intervals
        assert hasattr(AEATClient, 'CONNECT_TIMEOUT')
        assert hasattr(AEATClient, 'READ_TIMEOUT')
        assert AEATClient.CONNECT_TIMEOUT > 0
        assert AEATClient.READ_TIMEOUT > 0


class TestAEATXMLParsing:
    """Tests for AEAT response XML parsing."""

    def test_parse_success_response(self):
        """Test parsing successful AEAT response."""
        with patch('verifactu.services.aeat_client.HAS_REQUESTS', True):
            client = AEATClient(
                certificate_path='/path/to/cert.p12',
                certificate_password='secret',
            )

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b'''<?xml version="1.0"?>
                <soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
                    <soap:Body>
                        <EstadoEnvio>Correcto</EstadoEnvio>
                        <CSV>TESTCSV123</CSV>
                    </soap:Body>
                </soap:Envelope>'''
            mock_response.text = mock_response.content.decode()

            result = client._parse_response(mock_response)

            assert result.http_status == 200

    def test_parse_error_response(self):
        """Test parsing error AEAT response."""
        with patch('verifactu.services.aeat_client.HAS_REQUESTS', True):
            client = AEATClient(
                certificate_path='/path/to/cert.p12',
                certificate_password='secret',
            )

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b'''<?xml version="1.0"?>
                <soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
                    <soap:Body>
                        <EstadoEnvio>Incorrecto</EstadoEnvio>
                        <CodigoErrorRegistro>4001</CodigoErrorRegistro>
                        <DescripcionErrorRegistro>Invalid NIF</DescripcionErrorRegistro>
                    </soap:Body>
                </soap:Envelope>'''
            mock_response.text = mock_response.content.decode()

            result = client._parse_response(mock_response)

            assert result.http_status == 200

    def test_parse_malformed_xml(self):
        """Test parsing malformed XML response."""
        with patch('verifactu.services.aeat_client.HAS_REQUESTS', True):
            client = AEATClient(
                certificate_path='/path/to/cert.p12',
                certificate_password='secret',
            )

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b'not valid xml'
            mock_response.text = mock_response.content.decode()

            result = client._parse_response(mock_response)

            assert result.success is False
            assert result.code == 'PARSE_ERROR'
