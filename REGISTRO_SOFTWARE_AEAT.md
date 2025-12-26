# Guía de Registro del Software Verifactu ante AEAT

## Resumen Ejecutivo

Para que ERPlora Hub pueda ser usado legalmente como software de facturación en España bajo la normativa Verifactu (RD 1007/2023), el **fabricante del software** (ERPlora) debe emitir una **Declaración Responsable** certificando que cumple con los requisitos legales.

> **IMPORTANTE:** No existe un "registro" previo ante AEAT. Solo se requiere una **autocertificación** (Declaración Responsable) que debe estar disponible para los usuarios.

---

## 1. ¿Qué es la Declaración Responsable?

Es una **autocertificación** mediante la cual el productor (fabricante) del software certifica que su producto cumple con:

- Artículo 29.2.j) de la Ley General Tributaria (LGT)
- Real Decreto 1007/2023 (Reglamento Verifactu)
- Orden Ministerial HAC/1177/2024

### ¿Quién debe emitirla?

| Rol | ¿Debe emitirla? |
|-----|-----------------|
| **Productor/Fabricante** (ERPlora) | ✅ SÍ - Obligatorio |
| Comercializador/Revendedor | ❌ No, pero debe conservarla |
| Usuario final (cliente) | ❌ No, pero debe verificar que existe |

---

## 2. Contenido Obligatorio de la Declaración

Según el artículo 13.4 del Reglamento, debe incluir:

### A. Datos del Sistema Informático

| Campo | Valor para ERPlora |
|-------|-------------------|
| **Nombre del SIF** | ERPlora Hub |
| **Código identificador** | EH (máx. 2 caracteres alfanuméricos) |
| **Versión** | 1.0.0 (cada versión requiere su declaración) |
| **Descripción** | Sistema modular de gestión empresarial con módulo de facturación electrónica compatible con Verifactu |

### B. Características Técnicas

- **Tipología:** Aplicación web/desktop híbrida
- **Composición:**
  - Hub base (Django)
  - Módulo Verifactu (compliance AEAT)
  - Módulo Invoicing (facturación)
- **Funcionalidades principales:**
  - Generación de registros de facturación
  - Encadenamiento hash SHA-256
  - Generación de código QR
  - Transmisión a AEAT (modo VERI*FACTU)
  - Almacenamiento local (modo NO VERI*FACTU)
  - Registro de eventos (log seguro)
- **Modalidad de instalación:**
  - Cloud (SaaS)
  - Desktop (PyInstaller)

### C. Datos del Productor

| Campo | Valor |
|-------|-------|
| **Razón social** | [NOMBRE EMPRESA ERPlora] |
| **NIF/VAT** | [NIF de la empresa] |
| **Domicilio** | [Dirección completa] |
| **País** | [España / País UE] |
| **Email contacto** | support@erplora.com |

### D. Fecha y Lugar

- **Fecha de certificación:** [Fecha]
- **Lugar:** [Ciudad, País]

---

## 3. Dónde debe estar disponible

La Declaración Responsable debe estar visible en **dos lugares**:

### A. Dentro del propio software (obligatorio)

```
Hub → Módulo Verifactu → Settings → "Declaración Responsable"
```

Implementación sugerida:
- Botón/enlace en la página de Settings de Verifactu
- Abre un modal o PDF con la declaración completa

### B. Externamente (obligatorio)

Debe estar disponible para clientes y comercializadores:

- **Página web pública:** `https://erplora.com/legal/declaracion-responsable-verifactu`
- **PDF descargable:** Enlace en la documentación
- **Formato:** PDF, texto plano u otro formato estándar gratuito

---

## 4. Modelo de Declaración Responsable

```
═══════════════════════════════════════════════════════════════════════════════
                    DECLARACIÓN RESPONSABLE
           DEL SISTEMA INFORMÁTICO DE FACTURACIÓN

           Conforme al artículo 13 del Real Decreto 1007/2023
═══════════════════════════════════════════════════════════════════════════════

1. DATOS DEL SISTEMA INFORMÁTICO DE FACTURACIÓN (SIF)

   Nombre del SIF:              ERPlora Hub
   Código identificador:        EH
   Versión:                     1.0.0

   Descripción:
   Sistema modular de gestión empresarial (ERP) con capacidades de punto de
   venta (POS) y facturación electrónica. Incluye módulo Verifactu para
   cumplimiento de la normativa española de facturación (RD 1007/2023).

2. CARACTERÍSTICAS TÉCNICAS

   Tipología:                   Aplicación web y desktop

   Componentes principales:
   - ERPlora Hub (aplicación base)
   - Módulo Verifactu (compliance AEAT)
   - Módulo Invoicing (facturación)

   Funcionalidades Verifactu:
   ✓ Generación de registros de facturación (alta y anulación)
   ✓ Encadenamiento mediante hash SHA-256
   ✓ Generación de código QR verificable
   ✓ Transmisión automática a AEAT (modo VERI*FACTU)
   ✓ Almacenamiento local seguro (modo NO VERI*FACTU)
   ✓ Registro de eventos con integridad garantizada
   ✓ Gestión de contingencias y reintentos
   ✓ Exportación de registros en formato XML

   Modalidades de instalación:
   - Cloud (SaaS): Contenedor Docker gestionado
   - Desktop: Aplicación empaquetada (PyInstaller)

   Modalidades de funcionamiento Verifactu:
   - VERI*FACTU: Transmisión en tiempo real a AEAT
   - NO VERI*FACTU: Almacenamiento local con QR verificable

3. DATOS DEL PRODUCTOR

   Razón social:                [NOMBRE EMPRESA]
   NIF/VAT:                     [NÚMERO DE IDENTIFICACIÓN FISCAL]
   Domicilio:                   [DIRECCIÓN COMPLETA]
   Localidad:                   [CIUDAD]
   Código postal:               [CP]
   País:                        [PAÍS]

   Contacto técnico:
   Email:                       support@erplora.com
   Web:                         https://erplora.com

4. DECLARACIÓN

   El productor abajo firmante DECLARA RESPONSABLEMENTE que el Sistema
   Informático de Facturación arriba identificado:

   a) Cumple con lo dispuesto en el artículo 29.2.j) de la Ley 58/2003,
      de 17 de diciembre, General Tributaria.

   b) Cumple con los requisitos establecidos en el Real Decreto 1007/2023,
      de 5 de diciembre, por el que se aprueba el Reglamento que establece
      los requisitos que deben adoptar los sistemas y programas informáticos
      o electrónicos que soporten los procesos de facturación de empresarios
      y profesionales.

   c) Cumple con las especificaciones técnicas establecidas en la Orden
      HAC/1177/2024.

   d) Garantiza la integridad, conservación, accesibilidad, legibilidad,
      trazabilidad e inalterabilidad de los registros de facturación.

   e) No permite la alteración de los registros de facturación una vez
      generados.

   f) Permite el acceso a los registros de facturación por parte de la
      Administración Tributaria.

5. VIGENCIA

   Esta declaración responsable es válida para la versión indicada del
   software. Cualquier actualización que afecte a las funcionalidades
   relacionadas con la facturación requerirá una nueva declaración.

6. FIRMA

   Lugar y fecha:               [CIUDAD], [FECHA]



   Firmado: ___________________________
            [NOMBRE DEL REPRESENTANTE LEGAL]
            [CARGO]


═══════════════════════════════════════════════════════════════════════════════
                    Documento generado conforme a los ejemplos
                    publicados por la Agencia Tributaria (AEAT)

   Referencia: https://sede.agenciatributaria.gob.es/Sede/iva/
               sistemas-informaticos-facturacion-verifactu.html
═══════════════════════════════════════════════════════════════════════════════
```

---

## 5. Requisitos Técnicos que debe cumplir el Software

Para poder emitir la Declaración Responsable, ERPlora Hub debe cumplir:

### Obligatorios

| Requisito | Estado en ERPlora |
|-----------|-------------------|
| Generación de registros de facturación | ✅ Implementado |
| Encadenamiento hash SHA-256 | ✅ Implementado |
| Código QR en facturas | ✅ Implementado |
| Inalterabilidad de registros | ✅ Implementado |
| Registro de eventos (log) | ✅ Implementado |
| Acceso AEAT a registros | ✅ Implementado |
| Firma electrónica de registros | ⚠️ Pendiente verificar |
| Transmisión a AEAT (modo Verifactu) | ⚠️ Pendiente testing |

### Funcionalidades requeridas

- [x] Generar registro de alta por cada factura
- [x] Generar registro de anulación
- [x] Incluir hash del registro anterior (encadenamiento)
- [x] Generar código QR con URL de verificación
- [x] Mantener log de eventos seguro
- [x] Permitir exportación de registros
- [ ] Firmar registros con certificado (modo NO VERI*FACTU)
- [ ] Transmitir a AEAT via SOAP/XML (modo VERI*FACTU)

---

## 6. Plazos Importantes

| Fecha | Hito |
|-------|------|
| **29 julio 2025** | Software debe estar adaptado y con Declaración Responsable |
| 1 enero 2026 | Obligatorio para sociedades (Impuesto de Sociedades) |
| 1 julio 2026 | Obligatorio para autónomos |

---

## 7. Sanciones por Incumplimiento

| Infracción | Sanción |
|------------|---------|
| Fabricante sin Declaración Responsable | Mínimo **150.000€** |
| Software no conforme | Hasta **50.000€** por ejercicio |
| Usuario con software no certificado | Responsabilidad compartida |

---

## 8. Pasos para ERPlora

### Paso 1: Verificar cumplimiento técnico
- [ ] Revisar que todas las funcionalidades están implementadas
- [ ] Realizar pruebas con el entorno de testing de AEAT
- [ ] Documentar las características técnicas

### Paso 2: Preparar la Declaración Responsable
- [ ] Rellenar el modelo con los datos de la empresa
- [ ] Revisar con asesor legal si es necesario
- [ ] Firmar por el representante legal

### Paso 3: Publicar la Declaración
- [ ] Incluir acceso desde el módulo Verifactu en el Hub
- [ ] Publicar en la web de ERPlora
- [ ] Proporcionar PDF descargable

### Paso 4: Mantener actualizada
- [ ] Nueva declaración por cada versión mayor
- [ ] Conservar todas las versiones durante el período de prescripción

---

## 9. Referencias Oficiales

- [Portal Verifactu AEAT](https://sede.agenciatributaria.gob.es/Sede/iva/sistemas-informaticos-facturacion-verifactu.html)
- [FAQ Declaración Responsable](https://sede.agenciatributaria.gob.es/Sede/iva/sistemas-informaticos-facturacion-verifactu/preguntas-frecuentes/certificacion-sistemas-informaticos-declaracion-responsable.html)
- [Ejemplos de Declaración Responsable (PDF)](https://sede.agenciatributaria.gob.es/static_files/Sede/Tema/IVA/Verifactu/EjemplosDeclaracionResponsable(V0.5.1).pdf)
- [Real Decreto 1007/2023](https://www.boe.es/buscar/act.php?id=BOE-A-2023-24840)
- [Orden HAC/1177/2024](https://www.boe.es/buscar/act.php?id=BOE-A-2024-21525)

---

## 10. Preguntas Frecuentes

### ¿Necesito registrar el software en algún sitio?
**No.** No existe registro previo. Solo debes emitir la Declaración Responsable y tenerla disponible.

### ¿Puedo registrar el software desde una empresa de la UE (no española)?
**Sí.** El fabricante puede estar en cualquier país de la UE. Solo necesitas un NIF/VAT válido.

### ¿El certificado digital del software es el mismo que el del usuario?
**No.** El certificado para firmar facturas es del usuario (empresa que factura). La Declaración Responsable es del fabricante del software.

### ¿Qué pasa si actualizo el software?
Cada versión que afecte a funcionalidades de facturación requiere una nueva Declaración Responsable.

### ¿Necesito firma electrónica en la Declaración?
**No es obligatorio.** Solo debe indicar fecha y lugar de suscripción. Opcionalmente puede firmarse electrónicamente.

---

*Documento actualizado: Diciembre 2024*
*Versión: 1.0*
