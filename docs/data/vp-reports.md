# Reportes PAT de VirtualPOS (VP-PAR-02 / RJ-04)

> Sprint 5A. Importador de los reportes `TransaccionesPAT-VirtualPOS-*.csv` y `SuscriptoresPAT-VirtualPOS-*.csv` del portal.
> Origen del diseño: `docs/planning/auditoria-2026-10-29/` (paridad CRM vs reportes, glosa de rechazo) y decisión **D6**
> (el histórico de glosas de VirtualPOS sale de estos reportes, con `capture_source = 'report_pat'`).
> Patrón seguido: importador de reportes de Toku (`toku_report_parser.py`, `toku_report_import.py`, TK-17/TK-18).

## 1. Diseño del modelo (por qué tablas propias)

Se evaluaron dos caminos para guardar lo que hoy solo vive en `raw_payload` o que no existe en el CRM:

| Opción | Efecto |
|---|---|
| A. Columnas nuevas en `vp_charges` / `vp_payments` / `vp_subscriptions` | Toca tablas grandes y calientes (`ALTER TABLE` sobre cientos de miles de filas en `crm`), las reescribe el sync nocturno (`upsert` que reemplaza la fila) y obliga a decidir qué fuente gana en cada columna. |
| **B. Tablas propias `vp_report_*` (elegida)** | Solo `CREATE TABLE` de tablas vacías: la migración no toca datos existentes y es reversible (`DROP TABLE`). El sync no las pisa. Cada fila conserva `source_generated_at` y el archivo que la cargó (trazabilidad y guarda de frescura). El ETL Core puede leerlas después sin cambiar `vp_*`. |

Se eligió B por ser la menos invasiva. Tablas (migración `20261029_0045`, modelo `app/models/vp_report.py`):

* `vp_report_files`: un archivo cargado. `file_sha256` **único** (el mismo archivo no se carga dos veces), `report_type`
  (`transacciones` | `suscriptores`), `filename` (solo el nombre), `rows_*`, rango de fechas (`window_start/end`), `generated_at`,
  `loaded_at`, `status` (`running` | `completed` | `failed`), `error_label` técnico y `uploaded_by_user_id`. **Sin contenido ni datos personales.**
* `vp_report_payments`: un cobro (clave `Id cargo`, `charge_external_id`, único). Guarda el `UUID transacción`
  (`payment_external_id`), código y glosa de rechazo, medio de pago por cobro (Débito/Crédito/Prepago), fecha de autorización,
  comisión, abono, fecha de abono, alias POS, hash del código de vendedor, origen de la suscripción y del cargo, y los últimos 4 dígitos.
* `vp_report_subscriptions`: una suscripción (clave `Id de suscripción`). Estado, fechas de alta y cancelación, plan, contadores de cargos,
  canal/origen, alias POS, hash del código de vendedor, tipo/marca/últimos 4 de la tarjeta y **motivo de rechazo de la suscripción**.

### Datos sensibles: decisiones

* **Nunca se leen** nombre, apellido, correo, RUT, teléfono, nacimiento, género ni dirección del cliente (el parser lee solo las columnas
  de la firma por posición).
* **Últimos 4 dígitos (`card_last4`)**: el proyecto ya los guarda en `vp_subscriptions.raw_payload.payment_method.last4CardDigit`, por eso se
  guardan. Un `CHECK` (`^[0-9]{4}$`) y la columna `VARCHAR(4)` impiden guardar más de 4 dígitos; el parser descarta cualquier valor que no
  sean exactamente 4 dígitos. Nunca PAN completo ni CVV.
* **Código de vendedor**: en el portal tiene forma de RUT (identificador de una persona). Se guarda solo como `seller_code_hash`
  (HMAC-SHA256 con el pepper `VP_REPORT_HASH_PEPPER`), nunca en claro. Sin pepper el campo queda NULL (y se avisa); el resto de la carga sigue.
  Nota: `vp_subscriptions.raw_payload.seller_id` ya contiene ese valor en claro (hallazgo previo al importador, no cambia con esta tarea).
* No hay `raw_payload` en ninguna de las tres tablas.
