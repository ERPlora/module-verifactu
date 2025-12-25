# Verifactu Module - ERPlora

## Overview

This module implements Spain's **VERI*FACTU** system for verifiable electronic invoicing, as mandated by:
- **Real Decreto 1007/2023** (5 December 2023) - RRSIF Regulation
- **Orden HAC/1177/2024** - Technical specifications

## Important Dates

| Milestone | Date |
|-----------|------|
| Software compliance deadline | **29 July 2025** |
| Corporate taxpayers (IS) | **1 January 2027** |
| Self-employed (autónomos) | **1 July 2027** |

> Note: Real Decreto-Ley 15/2025 postponed implementation to 2027.

---

## Quick Reference

### What is Verifactu?

Verifactu is a **mandatory electronic invoicing system** for businesses in Spain. It ensures invoices are verifiable and cannot be falsified.

### How does it work? (Simple Explanation)

1. **Every invoice gets a unique hash** (like a fingerprint)
2. **Each hash includes the previous one** (creating an unbreakable chain)
3. **Invoices are sent to AEAT** (Spanish Tax Agency) in real-time
4. **Customers can verify** invoices by scanning a QR code

```
Invoice 1     Invoice 2     Invoice 3
   ↓             ↓             ↓
Hash: AAA  →  Hash: BBB  →  Hash: CCC
              (uses AAA)    (uses BBB)
```

### Common Questions

| Question | Answer |
|----------|--------|
| What if internet is down? | Invoices are queued and sent when connection restores |
| What if I restore a backup? | Use Chain Recovery to sync with AEAT |
| What if AEAT is down? | System retries automatically with exponential backoff |
| Can I modify an invoice? | No, but you can cancel and create a new one |

### Key Navigation

| Where | What |
|-------|------|
| **Dashboard** | Overview and statistics |
| **Records** | All submitted invoices |
| **Contingency** | Queue management and recovery |
| **Settings** | Certificate and configuration |

---

## Technical Architecture

### System Modes

1. **VERI*FACTU Mode** (Recommended)
   - Real-time transmission to AEAT
   - QR code verification
   - No local record storage required
   - Automatic compliance validation

2. **NO VERI*FACTU Mode**
   - Local record storage
   - Periodic submission
   - Manual compliance responsibility

### Core Components

```
verifactu/
├── services/
│   ├── hash_service.py      # SHA-256 hash chain generation
│   ├── xml_service.py       # XML record generation (UTF-8)
│   ├── qr_service.py        # QR code generation for invoices
│   ├── aeat_client.py       # AEAT API client (SOAP/REST)
│   └── contingency.py       # Offline mode & retry logic
├── models.py                 # Database models
├── views.py                  # UI views
└── tests/                    # Comprehensive test suite
```

---

## Data Model

### Record Types

| Type | Description | Hash Fields |
|------|-------------|-------------|
| **Alta** | Invoice registration | NIF, Number, Date, Total, Previous Hash |
| **Anulación** | Invoice cancellation | Original record reference |
| **Evento** | System event | Event type, timestamp, details |

### Invoice Types (L2 List)

| Code | Description |
|------|-------------|
| F1 | Standard invoice |
| F2 | Simplified invoice (ticket) |
| F3 | Invoice substituting simplified |
| R1 | Rectifying invoice (Art. 80.1-2) |
| R2 | Rectifying invoice (Art. 80.3) |
| R3 | Rectifying invoice (Art. 80.4) |
| R4 | Rectifying invoice (other) |
| R5 | Rectifying simplified invoice |

### Tax Types (L1 List)

| Code | Description |
|------|-------------|
| 01 | General VAT |
| 02 | Reduced VAT |
| 03 | Super-reduced VAT |
| 04 | IGIC (Canary Islands) |
| 05 | IPSI (Ceuta/Melilla) |

---

## Hash Chain Implementation

### Algorithm: SHA-256

Each record contains a cryptographic hash that chains to the previous record, ensuring:
- **Integrity**: Any modification is detectable
- **Traceability**: Complete audit trail
- **Immutability**: Records cannot be altered without detection

### Hash Calculation Fields

**For Alta (Registration) Records:**
```python
hash_input = (
    f"IDEmisorFactura={nif}"
    f"&NumSerieFactura={invoice_number}"
    f"&FechaExpedicionFactura={date_ddmmyyyy}"
    f"&TipoFactura={invoice_type}"
    f"&CuotaTotal={total_tax}"
    f"&ImporteTotal={total_amount}"
    f"&Huella={previous_hash}"
    f"&FechaHoraHusoGenRegistro={timestamp_iso}"
)
hash_result = hashlib.sha256(hash_input.encode('utf-8')).hexdigest().upper()
```

**For Anulación (Cancellation) Records:**
```python
hash_input = (
    f"IDEmisorFactura={nif}"
    f"&NumSerieFactura={original_invoice_number}"
    f"&FechaExpedicionFactura={original_date}"
    f"&Huella={previous_hash}"
    f"&FechaHoraHusoGenRegistro={timestamp_iso}"
)
```

### First Record (Genesis)

The first record in a chain has no previous hash. Use empty string for `Huella` field.

---

## XML Structure

### Encoding: UTF-8

All XML must be encoded in UTF-8 and pass AEAT XSD validation.

### Sample Structure

```xml
<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:sf="https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/SuministroInformacion.xsd">
  <soapenv:Header/>
  <soapenv:Body>
    <sf:RegFactuSistemaFacturacion>
      <sf:Cabecera>
        <sf:ObligadoEmision>
          <sf:NombreRazon>Empresa Demo SL</sf:NombreRazon>
          <sf:NIF>B12345678</sf:NIF>
        </sf:ObligadoEmision>
      </sf:Cabecera>
      <sf:RegistroFactura>
        <sf:RegistroAlta>
          <sf:IDFactura>
            <sf:IDEmisorFactura>B12345678</sf:IDEmisorFactura>
            <sf:NumSerieFactura>F2025-0001</sf:NumSerieFactura>
            <sf:FechaExpedicionFactura>15-01-2025</sf:FechaExpedicionFactura>
          </sf:IDFactura>
          <sf:TipoFactura>F1</sf:TipoFactura>
          <sf:DescripcionOperacion>Professional services</sf:DescripcionOperacion>
          <sf:ImporteTotal>1028.50</sf:ImporteTotal>
          <sf:Encadenamiento>
            <sf:PrimerRegistro>N</sf:PrimerRegistro>
            <sf:RegistroAnterior>
              <sf:Huella>45A91BE76FA44C9BD3C72EF6E45F8A99...</sf:Huella>
            </sf:RegistroAnterior>
          </sf:Encadenamiento>
          <sf:SistemaInformatico>
            <sf:NombreRazon>ERPlora</sf:NombreRazon>
            <sf:NIF>B00000000</sf:NIF>
            <sf:NombreSistemaInformatico>ERPlora Hub</sf:NombreSistemaInformatico>
            <sf:IdSistemaInformatico>ERPLORA-001</sf:IdSistemaInformatico>
            <sf:Version>1.0.0</sf:Version>
          </sf:SistemaInformatico>
          <sf:FechaHoraHusoGenRegistro>2025-01-15T17:22:14+01:00</sf:FechaHoraHusoGenRegistro>
          <sf:Huella>E3F11B5822C90488BF3FE2D27901EC8F...</sf:Huella>
        </sf:RegistroAlta>
      </sf:RegistroFactura>
    </sf:RegFactuSistemaFacturacion>
  </soapenv:Body>
</soapenv:Envelope>
```

---

## QR Code Specification

### Content Format

The QR code contains a URL that allows customers to verify the invoice:

```
https://www2.agenciatributaria.gob.es/wlpl/TIKE-CONT/ValidarQR
  ?nif={issuer_nif}
  &numserie={invoice_number}
  &fecha={date_ddmmyyyy}
  &importe={total_amount}
```

### Display Requirements

- Must appear on all invoices with text "VERIFACTU"
- Minimum size: 2cm x 2cm
- Error correction level: M (15%)

---

## AEAT API Integration

### Endpoints

| Environment | Base URL |
|-------------|----------|
| **Production** | `https://www1.agenciatributaria.gob.es/wlpl/TIKE-CONT/ws/` |
| **Testing** | `https://prewww1.aeat.es/wlpl/TIKE-CONT/ws/` |

### Services

| Service | Operation | Description |
|---------|-----------|-------------|
| `SuministroLR` | `SuministroLRFacturasEmitidas` | Submit invoice records |
| `ConsultaLR` | `ConsultaLRFacturasEmitidas` | Query submitted records |

### Authentication

- **Certificate Required**: Qualified electronic certificate (FNMT, Camerfirma, etc.)
- **Format**: PKCS#12 (.p12/.pfx)
- **Standards**: ETSI EN 319 132 for signatures

### Request Limits

- Maximum 1,000 records per request
- Immediate transmission required (no batching at end of day)

---

## Contingency Plans

### Scenario 1: Internet Connection Failure

**Detection:**
```python
def check_connectivity():
    try:
        socket.create_connection(("www.agenciatributaria.gob.es", 443), timeout=5)
        return True
    except OSError:
        return False
```

**Response:**
1. Continue generating invoices with valid hash chain
2. Store records in local queue with status `PENDING_TRANSMISSION`
3. Retry transmission every 5 minutes
4. Alert user after 30 minutes of failure

**Recovery:**
1. When connection restored, send queued records in order
2. Validate AEAT response for each record
3. Update status to `TRANSMITTED` or `ERROR`

### Scenario 2: AEAT Service Unavailable

**Detection:**
- HTTP 503 Service Unavailable
- Timeout > 30 seconds
- SOAP Fault with service error

**Response:**
1. Log the error with timestamp and details
2. Store record with status `AEAT_UNAVAILABLE`
3. Implement exponential backoff retry:
   - 1st retry: 1 minute
   - 2nd retry: 5 minutes
   - 3rd retry: 15 minutes
   - 4th retry: 1 hour
   - Then every hour

**Recovery:**
1. AEAT publishes service status at sede.agenciatributaria.gob.es
2. Check status before bulk retry
3. Process queue in chronological order

### Scenario 3: Hash Chain Break (Database Restore)

This is one of the most common scenarios. When you restore a database backup, you lose the recent invoices that were already sent to AEAT.

**The Problem (Simple Explanation):**

Think of the hash chain as a **necklace of pearls** where each pearl is tied to the previous one:

```
Your backup has:     [F1] → [F2]               (last hash = BBB)
AEAT actually has:   [F1] → [F2] → [F3] → [F4]  (last hash = DDD)

If you create F5 using hash BBB, AEAT will reject it because they expect DDD
```

**Detection:**
```python
def validate_chain(records):
    for i, record in enumerate(records):
        if i == 0:
            expected_prev = ""
        else:
            expected_prev = records[i-1].hash
        if record.previous_hash != expected_prev:
            raise ChainCorruptionError(f"Record {record.id} has invalid chain")
```

**Response:**
1. STOP all invoice generation immediately
2. Alert system administrator
3. Go to **Verifactu > Contingency > Chain Recovery**

**Recovery Options:**

1. **Automatic (Recommended):** Query AEAT to get the last hash
   - The system calls `ConsultaLRFacturasEmitidas` SOAP service
   - AEAT returns your last submitted invoice and its hash
   - The system saves this hash as a "recovery point"
   - New invoices will use this recovered hash

2. **Manual:** Enter the hash yourself
   - Use this if automatic recovery fails
   - You can find your last hash in:
     - AEAT's Sede Electrónica portal
     - A previous backup that has the complete chain
     - The QR code of your last invoice

**How to Recover (Step by Step):**

1. Go to: **Verifactu > Contingency**
2. Click on **"Hash Chain Corruption"** accordion
3. Click **"Go to Chain Recovery"**
4. You'll see:
   - Your local last invoice and hash
   - AEAT's last invoice and hash (if queryable)
5. Choose an option:
   - Click **"Query AEAT"** for automatic recovery
   - Or enter the hash manually in the input field
6. Once recovered, you can continue creating invoices

**Important Notes:**
- The recovered hash is saved as a `ChainRecoveryPoint`
- New invoices will automatically use this hash
- You don't lose any data - AEAT already has the invoices
- Local database may show a "gap" but this is expected

### Scenario 4: Certificate Expiration

**Detection:**
- Check certificate expiry 30 days in advance
- Daily validation check

**Response:**
1. Alert administrator 30 days before expiry
2. Alert again at 14 days, 7 days, 3 days, 1 day
3. Block VERIFACTU transmission if expired (fall back to NO VERIFACTU mode)

**Recovery:**
1. Obtain new certificate from authorized provider
2. Install and configure in system
3. Test with AEAT staging environment
4. Resume normal operation

### Scenario 5: Duplicate Invoice Detection

**Detection:**
- AEAT returns error code for duplicate
- Local database constraint violation

**Response:**
1. Log the duplicate attempt
2. Query existing record status
3. If already transmitted: return existing record
4. If pending: wait and retry query

---

## Testing Strategy

### Unit Tests

Located in `tests/test_unit.py`:

```python
class TestHashService:
    def test_sha256_calculation(self):
        """Test correct SHA-256 hash generation"""

    def test_hash_chain_integrity(self):
        """Test hash chain links correctly"""

    def test_first_record_genesis(self):
        """Test first record has empty previous hash"""

    def test_hash_determinism(self):
        """Test same input produces same hash"""

class TestXMLService:
    def test_xml_encoding_utf8(self):
        """Test XML is valid UTF-8"""

    def test_xsd_validation(self):
        """Test XML passes AEAT XSD"""

    def test_required_fields_present(self):
        """Test all mandatory fields are included"""

class TestQRService:
    def test_qr_url_format(self):
        """Test QR contains valid AEAT URL"""

    def test_qr_size_minimum(self):
        """Test QR meets minimum size requirements"""
```

### Integration Tests

Located in `tests/test_integration.py`:

```python
class TestAEATIntegration:
    def test_connection_to_staging(self):
        """Test connection to AEAT staging environment"""

    def test_certificate_authentication(self):
        """Test authentication with certificate"""

    def test_submit_single_record(self):
        """Test submitting one invoice record"""

    def test_query_submitted_records(self):
        """Test querying previously submitted records"""

    def test_cancellation_record(self):
        """Test submitting cancellation record"""
```

### E2E Tests

Located in `tests/test_e2e.py`:

```python
class TestFullInvoiceFlow:
    def test_create_invoice_generates_verifactu_record(self):
        """Test invoice creation triggers Verifactu record"""

    def test_record_transmitted_to_aeat(self):
        """Test record is sent to AEAT"""

    def test_qr_code_appears_on_invoice(self):
        """Test QR code is added to invoice PDF"""

    def test_customer_can_verify_via_qr(self):
        """Test QR verification works"""

    def test_invoice_cancellation_flow(self):
        """Test cancellation creates proper record"""

    def test_offline_mode_and_recovery(self):
        """Test system works offline and syncs when online"""
```

---

## Configuration

### Settings (VerifactuConfig)

| Setting | Type | Description |
|---------|------|-------------|
| `enabled` | Boolean | Enable/disable Verifactu |
| `mode` | Enum | VERIFACTU or NO_VERIFACTU |
| `environment` | Enum | PRODUCTION or TESTING |
| `certificate_path` | String | Path to .p12 certificate |
| `certificate_password` | String | Certificate password (encrypted) |
| `software_name` | String | "ERPlora Hub" |
| `software_version` | String | Current version |
| `software_nif` | String | ERPlora company NIF |
| `retry_interval` | Integer | Minutes between retries |
| `max_retries` | Integer | Maximum retry attempts |

---

## Error Codes

### AEAT Response Codes

| Code | Description | Action |
|------|-------------|--------|
| 0 | Success | Record accepted |
| 1000 | Duplicate | Check existing record |
| 2000 | Invalid format | Fix XML and retry |
| 3000 | Invalid certificate | Check certificate |
| 4000 | Unauthorized | Check permissions |
| 5000 | Service error | Retry later |

### Internal Error Codes

| Code | Description |
|------|-------------|
| VF001 | Hash calculation failed |
| VF002 | Chain corruption detected |
| VF003 | XML generation failed |
| VF004 | Certificate not found |
| VF005 | Connection timeout |
| VF006 | Queue overflow |

---

## References

- [AEAT Verifactu Portal](https://sede.agenciatributaria.gob.es/Sede/iva/sistemas-informaticos-facturacion-verifactu.html)
- [AEAT Developer Documentation](https://www.agenciatributaria.es/AEAT.desarrolladores/)
- [Real Decreto 1007/2023](https://www.boe.es/eli/es/rd/2023/12/05/1007)
- [Orden HAC/1177/2024](https://www.boe.es/eli/es/o/2024/10/17/hac1177)
- [FAQ VERIFACTU](https://sede.agenciatributaria.gob.es/Sede/iva/sistemas-informaticos-facturacion-verifactu/preguntas-frecuentes.html)

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2025-12-25 | Initial implementation |

---

*Document maintained by ERPlora Team*
