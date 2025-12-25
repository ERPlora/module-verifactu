# Verifactu Module

Spanish electronic invoicing compliance (VERI*FACTU) for ERPlora Hub.

## Overview

This module implements Spain's **VERI*FACTU** system for verifiable electronic invoicing, as mandated by:
- **Real Decreto 1007/2023** (5 December 2023)
- **Orden HAC/1177/2024** - Technical specifications

## Key Dates

| Milestone | Date |
|-----------|------|
| Software compliance deadline | **29 July 2025** |
| Corporate taxpayers (IS) | **1 January 2027** |
| Self-employed (autónomos) | **1 July 2027** |

## Features

- **Hash Chain**: Cryptographic SHA-256 chain ensuring invoice integrity
- **Real-time Transmission**: Automatic submission to AEAT
- **QR Code Generation**: Verifiable codes on every invoice
- **Offline Mode**: Queue and retry when connectivity fails
- **Chain Recovery**: Restore hash chain after database backup
- **Certificate Management**: PKCS#12 certificate support
- **Dual Mode**: VERIFACTU (real-time) or NO VERIFACTU (local storage)

## Installation

This module is installed automatically via the ERPlora Marketplace.

**Dependencies**: Requires `invoicing` module.

## How It Works

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

## Configuration

Access settings via: **Menu > Verifactu > Settings**

| Setting | Description |
|---------|-------------|
| `mode` | VERIFACTU (real-time) or NO VERIFACTU (local) |
| `environment` | Testing or Production |
| `certificate_path` | Path to PKCS#12 certificate (.p12/.pfx) |
| `certificate_password` | Certificate password (encrypted) |
| `auto_transmit` | Automatically send records to AEAT |
| `retry_interval` | Minutes between retry attempts |

## Navigation

| Section | Description |
|---------|-------------|
| **Dashboard** | Overview, statistics, and alerts |
| **Records** | All Verifactu records (submitted invoices) |
| **Contingency** | Queue management and chain recovery |
| **Events** | Audit log of all system events |
| **Settings** | Certificate and configuration |

## Invoice Types (AEAT L2 List)

| Code | Description |
|------|-------------|
| F1 | Standard invoice |
| F2 | Simplified invoice (ticket) |
| F3 | Invoice substituting simplified |
| R1-R5 | Rectifying invoices |

## Models

| Model | Description |
|-------|-------------|
| `VerifactuConfig` | Module configuration |
| `VerifactuRecord` | Invoice records with hash chain |
| `VerifactuEvent` | Audit log entries |
| `ContingencyQueue` | Pending transmissions |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Dashboard with statistics |
| `/records/` | GET | List all records |
| `/records/<id>/` | GET | Record detail with QR |
| `/settings/` | GET/POST | Configuration |
| `/contingency/` | GET | Queue status |
| `/recovery/` | GET | Chain recovery wizard |
| `/api/health/` | GET | System health check |
| `/api/verify-chain/` | POST | Validate hash chain |

## Contingency Handling

### Offline Mode
When internet is unavailable, invoices are queued locally and transmitted when connection restores.

### Chain Recovery
If you restore a database backup, use **Contingency > Chain Recovery** to sync with AEAT and recover the last valid hash.

## Certificate Requirements

- **Type**: Qualified electronic certificate (FNMT, Camerfirma, etc.)
- **Format**: PKCS#12 (.p12 or .pfx)
- **Standards**: ETSI EN 319 132

## Permissions

| Permission | Description |
|------------|-------------|
| `verifactu.view` | View records and status |
| `verifactu.manage` | Manage queue and retry |
| `verifactu.configure` | Change settings |
| `verifactu.transmit` | Manual transmission |

## Testing

Run tests with:
```bash
cd /path/to/hub
pytest modules/verifactu/tests/ -v
```

## References

- [AEAT Verifactu Portal](https://sede.agenciatributaria.gob.es/Sede/iva/sistemas-informaticos-facturacion-verifactu.html)
- [Real Decreto 1007/2023](https://www.boe.es/eli/es/rd/2023/12/05/1007)
- [Orden HAC/1177/2024](https://www.boe.es/eli/es/o/2024/10/17/hac1177)

## Technical Documentation

For detailed technical documentation including hash calculation algorithms, XML structure, AEAT API integration, and contingency scenarios, see [VERIFACTU.md](VERIFACTU.md).

## License

MIT

## Author

ERPlora Team - support@erplora.com
