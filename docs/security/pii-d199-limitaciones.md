# d199: datos personales, cambios aplicados y limitaciones conocidas

> 2026-11-13. Decisión d199 (opción a): «Corregir R3 ya, enmascarar R1 en vistas y exportaciones, SEC-02 en S7 y
> documentar R2, R4 y R5 como limitaciones; sin migraciones». Los riesgos vienen del inventario SEC-01
> (`docs/security/pii-inventory.md`, rama `docs/s6-sec-sync`). Este documento no contiene datos personales.

## Numeración

La ficha d199 y el inventario SEC-01 no numeran igual el CSV del Recuperador:

| Ficha d199 | Inventario SEC-01 | Riesgo |
|---|---|---|
| R1 | R1 | `tch_suscripciones.numero_cuenta` en claro |
| R3 | **R4** | CSV del Recuperador VirtualPOS con datos personales sin `export.pii` |
| R2 | R2 | `stg_*_webhook_events` sin enmascarar ni purgar |
| R4 | **R3** | `raw_payload` y `source_records.payload` conservan datos personales |
| R5 | R5 | `soporte` y `ejecutivo` ven datos personales de todos los canales |

Se corrigió lo que la ficha describe (el CSV del Recuperador) y se documentan como limitaciones los otros tres. Si la
intención era otra, hay que revisarlo en la Bandeja antes de integrar la rama.

## Corregido en esta rama (`fix/pii-r1-r3`)

- **Cuenta bancaria (R1).** La base no cambia: `numero_cuenta` sigue guardada completa. Al leer, la API solo entrega
  los últimos 4 dígitos (`••••1234`; una cuenta de 4 dígitos o menos sale solo como `••••`):
  ficha y listado de suscripciones TCH (`numero_cuenta`), registros `crm` (`raw_payload`), fichas de staging y
  `source_records`. Se cubren también las claves con tilde o símbolo («Número Cuenta», «N° Cuenta»), que el saneador
  de payloads no reconoce y por eso pueden estar en `tch_suscripciones.raw_payload` y en su copia consolidada.
  Ninguna exportación tiene columna de cuenta. No existe un permiso para verla completa.
  Código: `app/services/account_masking.py`.
- **CSV del Recuperador (R3 de la ficha).** `virtualpos.recovery.export` habilita la descarga; RUT, nombre, correo y
  teléfono exigen además `export.pii`, como el resto de las exportaciones. Sin él, esas columnas se omiten y la
  auditoría registra `pii_included: false`.

## Limitaciones conocidas (sin cambio en esta rama)

- **R2: webhooks históricos sin enmascarar.** Las tablas `stg_vpos_webhook_events`, `stg_toku_webhook_events` y
  `stg_payku_webhook_events` conservan payloads crudos, cabeceras e IP de antes de la migración 0049. No se escriben
  más, pero nadie las purga. Vaciarlas borra datos y es decisión del usuario.
- **R3 del inventario (R4 de la ficha): payloads de proveedor con datos personales.** `raw_payload` de las tablas de
  canal y `crm`, y `source_records.payload`, guardan nombre, correo, RUT y teléfono tal como llegan; el saneador solo
  quita credenciales de pago. Se acepta por diseño (auditoría y reproceso). Además, el saneador compara claves sin
  plegar tildes; esta rama enmascara la cuenta al leer, pero no limpia lo ya guardado ni cambia la carga.
- **R5: roles de lectura con datos personales.** `soporte` y `ejecutivo` heredan todos los permisos `.view` y ven RUT,
  nombre, correo y teléfono en pantalla en todos los canales. Reducirlo requiere definir el mínimo con la jefatura.

## SEC-02 (modo demo), planificado para S7

La demo será sobre la producción local, con datos reales. Hoy lo único que oculta datos es el permiso. SEC-02 debe
enmascarar en la respuesta de la API (no solo en el front) RUT, nombres, correos, teléfonos, dirección, cuenta y notas
libres en listados, fichas, búsqueda, Recuperador e identidad; forzar a NULL las columnas personales en todas las
exportaciones; cubrir `raw_payload` donde se muestre; y tener pruebas de que, encendido, ninguna pantalla ni CSV
muestra el dato en claro. Hasta entonces, R5 y el Recuperador en pantalla siguen mostrando datos a quien tenga el
permiso de vista.
