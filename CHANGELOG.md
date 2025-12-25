# Changelog

All notable changes to the Verifactu module will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2025-12-25

### Added

- Initial release of Verifactu module
- **Core Features**
  - SHA-256 hash chain implementation for invoice integrity
  - Real-time transmission to AEAT (Spanish Tax Agency)
  - QR code generation for invoice verification
  - Dual mode support: VERIFACTU and NO VERIFACTU

- **Models**
  - `VerifactuConfig`: Module configuration with certificate management
  - `VerifactuRecord`: Invoice records with hash chain
  - `VerifactuEvent`: Audit log for all system events
  - `ContingencyQueue`: Queue for pending transmissions

- **Services**
  - `HashService`: SHA-256 hash calculation and chain validation
  - `XMLService`: AEAT-compliant XML generation (UTF-8)
  - `QRService`: QR code generation with verification URL
  - `AEATClient`: SOAP/REST client for AEAT API
  - `ContingencyManager`: Offline mode and retry logic
  - `RecoveryService`: Hash chain recovery from AEAT

- **Views**
  - Dashboard with statistics and alerts
  - Records list with search and filters
  - Record detail with QR code display
  - Contingency management and queue status
  - Chain recovery wizard
  - Settings configuration

- **Internationalization**
  - English translations (base)
  - Spanish translations

- **Documentation**
  - Comprehensive technical documentation (VERIFACTU.md)
  - README with quick start guide

### Technical Details

- Compliance with Real Decreto 1007/2023
- Compliance with Orden HAC/1177/2024
- Support for PKCS#12 certificates (.p12/.pfx)
- Testing and Production AEAT environments
- Exponential backoff retry logic
- Automatic certificate expiry alerts

---

## [Unreleased]

### Planned

- Integration with Invoicing module for automatic record creation
- Bulk record submission
- Advanced reporting and analytics
- Certificate renewal notifications
- Multi-NIF support for franchises
