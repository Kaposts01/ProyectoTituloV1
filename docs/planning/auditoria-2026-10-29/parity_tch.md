# Paridad CRM vs reportes TCH (auditoria de solo lectura, 2026-10-29)

Alcance: carpeta `CRM_reportes\TCH` (30 .xlsx) frente a la base `crm` (tablas `tch_*`, `core_*`, canonicas). Solo lectura: agregados por script (openpyxl read_only), sin imprimir filas personales, sin tocar `.env`, sin Alembic, sin escrituras. Scripts y salidas intermedias en el scratchpad (`tch_*.py`, `tch_agg_out/`, `tch_db_out.txt`, `tch_cmp_out.txt`).

Incidente de la propia auditoria: una sonda de cabeceras (mala heuristica de deteccion de fila de encabezado en el cierre Dic 2022) imprimio una vez en la consola de la sesion una fila de datos de un socio (nombre, RUT, email, direccion) y tres etiquetas con datos. No se escribio en el repo ni en ningun documento; los JSON intermedios con esas etiquetas se borraron y se regeneraron con deteccion estricta. Hay que tratarlo como exposicion en el contexto de la sesion.

## 1. Inventario de archivos

- 30 archivos .xlsx (mas `desktop.ini`). Cierres de diciembre 2017 a 2025 (9), mensuales enero a diciembre 2025 (12, nombre "NN - TCH IG MES 2025"), mensuales enero a septiembre 2026 (9, nombre "AAAAMMDD TCH IG MES 2026"). Cubre dic 2017 → sep 2026. NO falta agosto ni septiembre 2026 (existen); lo unico pendiente es octubre 2026, que se cierra al terminar el mes (hoy 29-oct).
- Duplicado exacto: `12 - TCH IG DICIEMBRE 2025 (1).XLSX` y `20260101 TCH IG DICIEMBRE 2025.XLSX` tienen el mismo MD5 (10.729.991 bytes). Contenido identico.
- Libro de 33 hojas (34 en los de dic 2017 y dic 2025): KPI, VIGENTES, ELIMINADOS, FLUJO MANDATOS CANT, FLUJO MANDATOS MONTO, HISTORICO RECAUDACION CAN, HISTORICO RECAUDACION FLUJO, EFICIENCIA ENT, ENT RECHAZOS, CONSOLIDADO + 15 hojas por centro de costo (TOC, REG, WT, CP, CE, BB, VV, CHD, CC9..CC15), CARGOS ACEPTADOS, CARGOS RECHAZADOS, RECHAZOS, RESUMEN CARTERA VIGENTE, RECHAZADOS, DIA CARGO, ENVIADOS BANCO, TABLAS.
- Hojas de detalle (fila de encabezado verificada: filas 5-7 son rotulos de grupo y de columna; datos desde fila 8):
  - VIGENTES / ELIMINADOS / RECHAZADOS: 104 columnas (101 en RECHAZADOS). Grupos: Centro Costo, Estrategia, Origen/Campana, Lugar Captacion, Captador, Ficha DUES, Mandato DUES, Folio, SOCIO (Rut, Referencia, Nombre, Apellido, Fecha Nacimiento, Profesion, Tipo Socio, Ley, Reajuste), DATOS TITULAR DE CUENTA (Personalidad, Rut, Referencia, Nombre, Apellidos), ANTECEDENTES Y ESTADO MANDATO (Firma, Tipo Mandato, Banco, Tipo Cuenta, Numero Cuenta, Ingreso, Entrega Banco, Fecha Activacion, Fecha Rechazo, Fecha Eliminado, ESTADO, Motivo, Solicitado Por), TELEFONOS Y DIRECCION (Telefonos, eMail, Direccion, Numero, Casa/Depto, Villa/Pob, Comuna, Ciudad, Region), MANDATO ANTERIOR (N, Fecha/Monto Primer Cobro), MANDATO ACTUAL (Moneda, Monto Vigente, Equivalente en Pesos, Fecha/Monto Primer Cobro, Diferencia), APORTES ACUMULADOS (Cuotas cobradas, Monto cobrado, Cuotas, Monto, Promedio Donacion, Meses continuos sin aporte), PERMANENCIA (Meses, Anos, Mes), 12 bloques "N / Estado / Monto" de los ultimos 12 meses (cols 62-97), CANTIDAD, TIPO CARGO SIN ESTADO, ENTIDAD, NVO, RECH MES, ELI MES.
  - CARGOS ACEPTADOS (20 cols) y CARGOS RECHAZADOS (21 cols): Numero Ficha, Numero Mandato, Tipo Mandato, Entidad Recaudadora, Centro Costo, Origen, Captador, Ley, Rut, Nombre, Apellido, Transaccion (Normal / Reintento), Numero Pagos del Mandato, DETALLE DEL PAGO: Periodo (numerico 1..n, NO es un mes), N Cuota, Cuota Mes (el mes real, p. ej. "SEPT 26"), Moneda, Monto Cuota, TOTAL CARGADO/RECHAZADO, Fecha Cobro/Intento, Motivo (solo rechazados).

Filas de datos por archivo (solo conteo; VIG = VIGENTES, EL = ELIMINADOS, RE = RECHAZADOS mandatos, CA/CR = cargos aceptados/rechazados del mes):

| Archivo | VIG | EL | RE | CA | CR | Nota |
|---|---|---|---|---|---|---|
| Dic 2017 | 7.129 | 2.953 | 127 | 4.865 | 1.576 | primer reporte; control mensual desde 2017-01 |
| Dic 2018 (nombre 20190104) | 12.376 | 4.055 | 305 | 10.018 | 1.985 | nombre con fecha 2019-01-04 |
| Dic 2019 | 11.203 | 2.912 | 168 | 9.142 | 1.820 | |
| Dic 2020 | 9.687 | 2.153 | 46 | 8.278 | 1.269 | |
| Dic 2021 | 9.797 | 821 | 136 | 8.420 | 1.130 | |
| Dic 2022 | 9.107 | 984 | 190 | 7.079 | 1.403 | encabezado desplazado una fila (leaf en fila 7) |
| Dic 2023 | **hoja VIGENTES distinta (tabla numerica de 11 columnas, sin cartera)** | 795 | 360 | 6.432 | 1.611 | sin detalle de vigentes |
| Dic 2024 | 10.647 | 1.781 | 617 | 6.602 | 2.274 | |
| Ene-2025 .. Nov-2025 | 11.156 → 10.641 | 170 → 1.811 (acumulado del ano) | 615 → 1.292 | 6.669 → 6.383 | 2.392 → 2.324 | |
| Dic 2025 (x2 identicos) | 10.547 | 1.905 | 1.292 | 6.326 | 1.552 | |
| Ene-2026 .. Sep-2026 | 10.475 → 9.690 | 72 → 857 | 1.292 | 6.193 → 5.644 | 2.318 → 2.094 | Sep-26: ACTIVO 8.277, PENDIENTE 113, RECHAZADO 1.292, ELIMINADO 8 |

- Rango de fechas: activacion de mandatos 2015-09-27 → 2025-07-17 (despues de jul-2025 no hay fechas de activacion: ingreso termina en may-2025, primer cobro nuevo solo ~230 casos jun-25..sep-26; la cartera baja de 11,5 mil a 9,7 mil). Cargos con fecha: 2017-11-01 → 2026-09-30 (solo 30 meses tienen detalle de cargo). Control mensual (HISTORICO RECAUDACION CAN/FLUJO): 2017-01 → 2026-09 (mas ceros hasta 2027-12).
- Cada cierre y cada mensual aporta una ventana de 12 meses de estado por mandato (cols 62-97). Por tanto la historia 2017-2026 por mandato-mes se reconstruye con los cierres (ano Y completo) salvo 2023 (ver 3.3).
- ¿Los mensuales 2025 duplican los cierres? Comparando (ficha, mes) del historial de 12 meses: mensual vs cierre Dic-2025 en meses compartidos coincide 99,97 % (ene a nov 2025: 3 a 10 diferencias por archivo); excepcion mayo-2025: 3.985 mandatos con estado distinto y 1.294 ausentes en el cierre (el mensual de mayo quedo con estados "en proceso" no consolidados). Contra Dic-2024 (meses 2024 compartidos) coinciden 99,98 %. Lo unico que aportan los mensuales y NO esta en el cierre: (a) el detalle de CARGOS del mes (fecha de cobro, entidad, Normal/Reintento, motivo de rechazo) y (b) ELIMINADOS acumulado del ano a esa fecha. Los 12 cargos mensuales de 2025 + los de 2026 son lo unico con granularidad de cobro; para los otros meses solo existe estado mensual por mandato.
- Aceptadas del historial coinciden con CARGOS ACEPTADOS (±2 por mes), pero RECHAZADA del historial es mucho mayor que CARGOS RECHAZADOS (p. ej. 2025-03: 4.168 vs 2.549) porque el historial repite cada mes un "Rechazada" para los ~1.300 mandatos de la hoja RECHAZADOS que nunca cobraron.
- Control oficial (HISTORICO RECAUDACION CAN) = filas de CARGOS ACEPTADOS/RECHAZADOS del mes (p. ej. 2026-09: 5.644 / 2.094; 2025-03: 6.733 / 2.549). Es la verdad para conteos y montos.

## 2. Mapeo reporte → CRM (cadena actual)

Excel → `scripts/etl_tch.py` (CLI `--mode full|incremental` y `import_incremental_file` usado por `POST /api/v1/tch/import-report`, TCH-07, solo rol admin, 250 MiB, tarea de fondo en el proceso API) → `tch_clientes`, `tch_suscripciones`, `tch_transacciones`, `tch_recaudacion_mensual`, catalogos (`tch_bancos`, `tch_origenes`, `tch_centros_costo`, `tch_tipos_mandato`) → `app/services/channel_consolidation.py` (`clients`, `subscriptions`, `charges`, fuente `tch`) y `app/services/core_tch_etl.py` (`external_identities`, `core_client_attributes`, `core_subscriptions`, `core_payments`; TCH no genera `core_charges`) → rutas `/api/v1/tch/*` y pagina `/tch`. El job nocturno (`sync_all`) solo consolida; no existe ingesta automatica de Excel. Pruebas: `tests/test_etl_tch.py`, `tests/test_tch_import.py`.

## 3. Hallazgos de paridad (medidos en `crm`)

Base `crm` (produccion local). Cantidades: tch_clientes 28.982; tch_suscripciones 29.295 (VIGENTE 8.788, ELIMINADA 19.216, RECHAZADA 1.291); tch_transacciones 1.472.231; tch_recaudacion_mensual 128 periodos; core_payments tch 1.472.231; canonicas `charges` tch 1.472.231, `subscriptions` 29.295, `clients` 28.982; core_charges tch 0.

### 3.1 Lo que SI cuadra
- Fichas distintas en los 30 reportes = 29.295 = tch_suscripciones (estado final igual a simular el ETL en orden: 19.216 / 8.788 / 1.291). RUT distintos en reportes 28.972 vs 28.982 clientes (+10/11 titulares sin mandato propio).
- `tch_recaudacion_mensual` coincide al 100 % con HISTORICO RECAUDACION CAN para todos los meses con control.
- Los 22 bancos, 22 origenes, 8 centros de costo, 7 tipos de mandato estan en catalogo.

### 3.2 Tabla de brecha por campo (hoja VIGENTES/ELIMINADOS/RECHAZADOS y CARGOS)

| Campo del reporte | Destino actual | Estado | Observacion |
|---|---|---|---|
| Ficha DUES / Mandato DUES | numero_ficha / numero_mandato | OK | 100 % |
| Rut socio | tch_clientes.rut / sus.cliente_rut | OK con riesgo | 356 RUT con formato no estandar; 303 RUT con >1 ficha (max 10) |
| Nombre, Apellido, Fecha nacimiento (58 %), Profesion (3 %), Tipo socio | tch_clientes | OK | Tipo socio es constante "SOCIO" |
| eMail (88 %), Telefonos (87 %), Direccion+Numero+Casa+Villa, Comuna, Ciudad (98 %) | tch_clientes | OK en tch_*; PERDIDO en canonicas | `clients` canon tch: 0 con email/telefono (GAP-TCH-02); core_client_attributes si trae 24.906 email / 25.678 telefonos |
| Region (98 %) | — | NO CARGADO | |
| Personalidad (Natural 9.666 / Juridica 24) | tipo_persona | INCORRECTO | ETL fija "Natural" para todos (28.982) |
| Titular de cuenta (Rut, Nombre, Apellidos; difiere del socio en 302 mandatos del ultimo reporte) | cliente aparte sin vinculo | PARCIAL | se crea cliente titular pero no hay columna titular_rut en la suscripcion; 11 clientes huerfanos |
| Referencia (Sr/Sra), Folio (100 %), Solicitado Por | — | NO CARGADO | |
| Centro Costo, Origen/Campana (97 %), Captador (70 %) | centro_costo, origen, captador | OK | |
| Estrategia (95 %) | tch_centros_costo.estrategia | NO CARGADO | columna existe y esta vacia (0 de 8) |
| Lugar Captacion (47 %) | — | NO CARGADO | |
| Firma, Tipo Mandato, Banco, Tipo Cuenta (Cta Cte / Cuenta RUT / TC / Vista), Numero cuenta | sus.* | OK | numero_cuenta se guarda enmascarado; revisar politica PII |
| Ingreso (fecha, 100 %) | fecha_ingreso | NO CARGADO | columna existe, 0 filas |
| **Monto Vigente (100 %)** | **monto** | **ERROR** | `c_monto` toma la columna "Ingreso" (fecha) → `monto` NULL en 29.295/29.295; `core_subscriptions.amount` y `subscriptions.amount` NULL en el 100 % de TCH |
| Moneda Vigente (Pesos 9.689 / UF 1) | — | NO CARGADO | core usa `reajuste=="UF"` para la moneda (campo equivocado) |
| Equivalente en Pesos | equivalente_pesos | OK | 100 % |
| Entrega Banco, Fecha Activacion, Fecha Rechazo, Fecha Eliminado | fecha_* | OK | activacion vacia en 2.280 ELIMINADAS y 116 VIGENTES; desde jul-2025 la fuente ya no trae activaciones |
| ESTADO (Activo / Pendiente / Rechazado / Eliminado) | estado | PARCIAL | estado se infiere de la HOJA; los 113 "Pendiente" quedan como VIGENTE |
| Motivo | razon_baja | OK | |
| Ley (0,2 %), Reajuste ("SI" 3 %) | ley, reajuste | OK | |
| Mandato anterior (N, fecha/monto primer cobro), Mandato actual (fecha/monto primer cobro, diferencia) | — | NO CARGADO | |
| Aportes acumulados (cuotas cobradas, monto cobrado, promedio donacion, meses continuos sin aporte), Permanencia (meses, anos) | — | NO CARGADO | util para churn/LTV; hoy se recalcula |
| Cantidad, Tipo cargo sin estado, Entidad (codigo), NVO / RECH MES / ELI MES | — | NO CARGADO | |
| 12 bloques mensuales N cuota / Estado / Monto | tch_transacciones (tipo HISTORIAL_MENSUAL) | CARGADO con defectos | sin fecha de cobro (1.208.584 filas con fecha_cargo NULL); ver 3.3 |
| CARGOS: Entidad Recaudadora, Transaccion (Normal/Reintento), Pagos del Mandato, N Cuota, Fecha Cobro/Intento, Motivo | entidad, tipo_transaccion, total_cuotas, numero_cuota, fecha_cargo, razon_rechazo | OK | |
| CARGOS: **Cuota Mes** ("SEPT 26") | — | **NO LEIDO** | es el periodo real; el ETL intenta parsear la columna "Periodo" (numero) y cae al nombre del archivo |
| CARGOS: Moneda, Centro/Origen/Captador (duplicados) | — | no necesario | |
| codigo_respuesta | codigo_respuesta | SIEMPRE NULL (0 filas) | el reporte no trae codigo; solo Motivo |
| Hojas FLUJO MANDATOS CANT/MONTO (vigentes, altas, bajas por entidad desde 2021), RECHAZOS (motivo de rechazo de mandato), ENT RECHAZOS (motivos por entidad), KPI, EFICIENCIA ENT, DIA CARGO, ENVIADOS BANCO, RESUMEN CARTERA | — | NO CARGADAS | son controles oficiales agregados; solo se carga HISTORICO RECAUDACION |

### 3.3 Brecha por mes (transacciones; control = HISTORICO RECAUDACION)

Resumen anual (acep/rech de control = suma de meses; DB = filas `tch_transacciones` por periodo, excluye 108.585 filas con periodo NULL):

| Ano | Control acep | Control rech | DB acep | DB rech | DB otros (en proceso, nula, congelada) | Meses en cero en DB | Meses con DB >1,4x control |
|---|---|---|---|---|---|---|---|
| 2017 | 46.572 | 13.654 | 49.087 | 22.141 | 11.988 | 0 (control sin may/jun) | 1 |
| 2018 | 117.399 | 23.060 | 94.252 | 25.766 | 18.081 | 2 (may, jun) | 0 |
| 2019 | 112.422 | 23.881 | 109.668 | 28.110 | 13.472 | 2 | 2 |
| 2020 | 101.869 | 18.347 | 91.270 | 19.806 | 4.021 | 2 | 1 |
| 2021 | 100.803 | 14.030 | 89.138 | 14.780 | 2.825 | 2 | 1 |
| 2022 | 93.112 | 16.408 | 83.006 | 18.230 | 2.501 | 2 | 1 |
| 2023 | 77.541 | 17.491 | 8.512 | 5.313 | 2.424 | 2 | 0 (y 10 meses casi vacios) |
| 2024 | 78.842 | 23.022 | 103.875 | 46.809 | 15.581 | 2 | 5 |
| 2025 | 80.251 | 28.334 | 131.154 | 82.364 | 11.808 | 2 | 10 |
| 2026 (ene-sep) | 53.105 | 20.176 | 158.918 | 95.007 | 3.739 | 0 | 9 |

Totales: control aceptadas+rechazadas 2017-12..2026-09 = 1.006.528 intentos; DB total con periodo = 1.363.646 (+108.585 sin periodo = 1.472.231). Detalle por mes en `scratchpad\tch_cmp_out.txt`. Ejemplos: 2025-03 DB 12.883 acep / 7.738 rech vs control 6.733 / 2.549; 2026-01 DB 24.361 / 12.389 vs 6.193 / 2.318 (el doble: cierre dic-2025 etiquetado como 2026-01); 2019-01 DB 19.905 vs 9.987.

Estados (DB vs fuente): DB ACEPTADA 999.131, RECHAZADA 386.660, EN PROCESO 28.289, NULA 58.120, CONGELADA 31. Suscripciones: DB VIGENTE 8.788 vs reporte Sep-2026 sin RECHAZADO = 8.398 (ACTIVO 8.277 + PENDIENTE 113 + ELIMINADO 8); la diferencia son 387 fichas "fantasma" que quedaron VIGENTE por ultima aparicion en el cierre 2020 (376) o 2021 (11) y no aparecen mas ni en ELIMINADOS.

Clientes unicos por mes: el ETL no guarda historial de cartera por mes (solo ultimo estado); la serie mensual oficial de vigentes vive en FLUJO MANDATOS CANT (desde ene-2021) y en el bloque de 12 meses, no cargada. Altas (fecha_activacion) por mes existen en DB hasta 2025-07 y coinciden con la fuente (cuya propia serie se corta en jul-2025).

### 3.4 Causas raiz (con evidencia)
1. **Periodo de los CARGOS mal asignado.** `_transform_transacciones` busca la columna "Periodo" (numero 1..n) → `_norm_periodo` devuelve None → cae a `_periodo_from_filename` (8 digitos de la fecha del archivo). Efectos: (a) los 12 mensuales 2025 ("NN - TCH IG ...") no tienen fecha en el nombre → 108.585 filas con `periodo` NULL (80.251 acep + 28.334 rech = exactamente el total 2025 del control, pero sin mes); su dedupe_key queda "ficha||cuota|estado|monto" y puede colisionar entre meses; (b) los archivos cuyo nombre lleva la fecha del dia siguiente quedan en el mes equivocado: `20190104` (Dic 2018 → 2019-01), `20260101` (Dic 2025 → 2026-01), `20260301` (Feb 2026 → 2026-03). Debe leerse "Cuota Mes".
2. **dedupe_key inestable (GAP-TCH-07 materializado).** `numero_cuota` se guarda como texto de lo que devuelva pandas: `12` o `12.0` segun si la columna tiene NaN. En DB: 905.235 filas HISTORIAL con sufijo ".0" y 303.345 enteras; ignorando la cuota hay 238.092 filas sobrantes (20 % del historial). La misma cuota/mes aparece dos veces cuando se cargan archivos distintos.
3. **Carga incremental sin memoria de periodos.** `import_incremental_file` (ruta TCH-07) usa `loaded_history_periods=set()`: cada mensual vuelve a insertar 12 meses de historial; con la clave inestable de (2) se duplica (meses 2024-08 a 2026-08 con 2x).
4. **Historial y cargos se suman.** Un mismo (ficha, mes) existe como HISTORIAL_MENSUAL (sin fecha) y como cargo Normal/Reintento (con fecha) con claves distintas (el tipo no entra en la clave y el estado/monto si). Aceptadas del historial coinciden con cargos, rechazadas no (ver 1).
5. **Estado y monto dentro de la clave (DEC-04 / SYNC-GAP-02).** Clave = ficha|periodo|cuota|estado|monto: un rechazo seguido de un pago o un cambio de monto crea dos filas. En la fuente, la hoja CARGOS RECHAZADOS saca la cuota cuando el reintento paga (fichas presentes en ambas hojas del mismo mes: promedio 0,7 por archivo), asi que en la fuente cada cuota tiene UN estado final; las dobles filas del CRM salen de restatements entre archivos: en el historial hay 7.844 (ficha, mes) con mas de un estado entre archivos y 5.772 con ACEPTADA y RECHAZADA.
6. **Meses 05 y 06 de todos los anos sin filas** (y sin control 2017-05/06): el codigo actual SI parsea MAY/JUN (probado sobre Dic 2024, Dic 2017, Dic 2022); la carga en DB parece de una version anterior o de una mezcla de cargas. Tambien: `tch_recaudacion_mensual` tiene filas futuras con ceros (2026-10..2027-12, 14 periodos) y `archivo_origen` "20260831 TCH IG GESTION AGOSTO 2026.XLSX" no existe en disco (el nombre actual es sin "GESTION"). La base no coincide con el estado actual de la carpeta; se recomienda reconstruir.
7. **Dic 2023 sin cartera:** la hoja VIGENTES de ese archivo no es la cartera (tabla numerica de 11 columnas). No hay estado mensual de 2023 para mandatos vigentes (solo ELIMINADOS 795 + RECHAZADOS 360). DB 2023: 8.512 acep contra 77.541 del control. Se necesita ese archivo bien exportado o aceptar cobertura solo-control para 2023.
8. **Monto de suscripcion NULL** por mapeo de columna (ver tabla). Afecta MRR, `core_subscriptions.amount`, scripts `compare_mrr_*`.
9. **Estado de suscripcion** derivado de la hoja y por "ultima aparicion"; sin baja implicita (387 fantasmas) y sin tratar "Pendiente".
10. **Core:** `core_payments` se inserta con `ON CONFLICT DO NOTHING` (no refleja cambios de estado) y `occurred_at` NULL para 1.208.584 pagos (82 %); sin `core_charges` ni periodo en `core_payments`; `charges.client_external_id` NULL en el 100 % de TCH (GAP-TCH-03). La consolidacion nocturna reprocesa 1,47 M filas (runs de 2 h; 1,94 M "records").

### 3.5 Tension RUT unico vs ADR-001 (GAP-TCH-01)
- Hechos: el reporte TCH no trae identificador de socio distinto del RUT; la ficha identifica el mandato, no la persona. En DB 303 RUT tienen mas de una ficha (max 10), 356 RUT tienen formato no estandar, 24 socios del ultimo reporte son juridicas, y la cuenta puede ser de un titular distinto al socio (302 en el ultimo reporte).
- ADR-001 prohibe RUT como clave transversal, no como clave natural dentro del canal. Recomendacion: mantener `UNIQUE(rut)` en `tch_clientes` como llave natural del proveedor (equivale a `external_id` en `external_identities`, ya hecho: 28.982 identidades con client_id), pero (a) dejar de poblar `clients.social_id=rut` como identidad canonica para matching (usar solo `external_identities` + `client_match_candidates`), (b) normalizar/validar RUT con checksum y aislar los no validos (extranjeros/pasaportes) en vez de colapsarlos, (c) modelar el titular de la cuenta en la suscripcion, (d) tipo_persona real. No requiere romper la unicidad actual.

### 3.6 DEC-04 / SYNC-GAP-02 (rechazo y pago posterior de la misma cuota)
Recomendacion con datos: una cuota = `(ficha, periodo_real, n_cuota)` con UN estado final (el que muestra el reporte, que ademas coincide con el control oficial); el rechazo previo se conserva como evento/atributo (`intentos`, `ultimo_motivo`, tipo Normal/Reintento) y no como fila aparte. Efecto estimado: elimina los ~5,8 mil pares (ficha, mes) con ambos estados mas todos los duplicados de formato de cuota. Cada reporte pasa a hacer UPSERT con "ultimo reporte gana" por la clave estable. Requiere la decision de negocio DEC-04; mientras tanto, arreglar TCH-PAR-01/02 es independiente y necesario.

## 4. Que falta para cargar 2017→2026 completo, idempotente
1. Arreglar claves y periodo (TCH-PAR-01/02/03) y el monto (TCH-PAR-05) antes de recargar.
2. Reconstruir `tch_*` en una sola transaccion desde los 29 archivos unicos (excluir el duplicado) en orden cronologico; ventana de 12 meses por archivo con "ultimo archivo gana" por (ficha, periodo, cuota).
3. Reconciliar automaticamente contra HISTORICO RECAUDACION (aceptadas/rechazadas por mes: cantidad y monto) y contra FLUJO MANDATOS (vigentes por mes desde 2021); falla si hay diferencia.
4. Cobertura esperada: estado mensual por mandato 2017-01→2026-09 salvo 2023 (cartera vigente); detalle de cobro con fecha solo en 30 meses; el resto = estado mensual sin fecha/entidad/motivo (limite de la fuente).
5. Re-materializar core (clientes, atributos, suscripciones, pagos) con upsert real.
6. Resultado esperado: del orden de 1,15 M estados mensuales (pares ficha-mes) con ~200 mil enriquecidos por cargo, en vez de 1.472.231 filas actuales.

## 5. Actualizacion mensual (oct-2026 en adelante)
- Hoy: el admin sube un .xlsx (TCH-07) que corre en un hilo del API (pandas relee cada hoja varias veces, ~30 s por lectura de hoja grande; riesgo de memoria con 10 MB de xlsx x 104 columnas), sin hash de archivo, sin deteccion del mes del reporte (usa el nombre), sin reconciliacion y sin rechazo de reportes ya cargados.
- Falta: detectar el mes desde el contenido (`Cuota Mes` / hoja KPI), tabla `tch_report_files` (sha256, mes, filas, resultado), carga idempotente por clave estable, reconciliacion con control tras cada carga (reporte en la UI), upsert de la ventana de 12 meses y de ELIMINADOS, y limpiar futuros con ceros.

## 6. Tareas priorizadas (propuesta)

| ID | Descripcion | Archivos | Esfuerzo | Riesgo |
|---|---|---|---|---|
| TCH-PAR-01 | Leer "Cuota Mes" como periodo real de CARGOS; eliminar fallback por nombre de archivo; test con nombres sin fecha y con fecha +1 dia | scripts/etl_tch.py (`_transform_transacciones`, `_periodo_from_filename`), tests/test_etl_tch.py | S | Bajo |
| TCH-PAR-02 | Normalizar `numero_cuota` a entero sin ".0" y total_cuotas; clave estable | scripts/etl_tch.py (`_norm_cuota`, `_dedupe_key`) | S | Medio (cambia claves: exige reconstruir) |
| TCH-PAR-03 | Cerrar DEC-04 y re-definir clave (ficha, periodo, cuota) con ultimo estado; migracion de unicidad y rebuild | models/tch.py, alembic, etl_tch.py, core_tch_etl.py, channel_consolidation.py, docs | M | Medio-alto (migracion + backfill en `crm`: la aplica el usuario) |
| TCH-PAR-04 | Separar historial mensual (`fuente`) de cobros; precedencia cargo > historial; tratar "Rechazada" de mandatos de la hoja RECHAZADOS como estado de mandato, no cobro | models/tch.py, etl_tch.py, routes/tch.py (summary) | M | Medio |
| TCH-PAR-05 | Mapear Monto Vigente y Moneda Vigente (monto, moneda); arreglar `_resolve_currency`; backfill de `amount` en core/canonicas | etl_tch.py, core_tch_etl.py, channel_consolidation.py | S | Bajo |
| TCH-PAR-06 | Estado de suscripcion desde columna ESTADO (Pendiente) y baja implicita para fichas ausentes del ultimo reporte (387) | etl_tch.py (`_load_suscripciones`) | S | Medio |
| TCH-PAR-07 | Recarga completa transaccional `--mode full` con verificacion post-carga y reporte de diferencias contra control (conteo y monto por mes) | etl_tch.py, nueva tabla/endpoint de conciliacion, tests | M | Medio |
| TCH-PAR-08 | Resolver hueco 2023: pedir reexportar VIGENTES Dic 2023 o documentar cobertura solo-control; excluir duplicado Dic 2025 | operacion + docs/integrations/tch.md | S | Bajo (dependencia del usuario) |
| TCH-PAR-09 | Cargar campos faltantes de suscripcion/cliente: estrategia, lugar captacion, folio, referencia, personalidad real, region, titular_rut/nombre, fecha_ingreso, mandato anterior, primer cobro, aportes acumulados, permanencia, flags NVO/RECH/ELI | models/tch.py, alembic, etl_tch.py, schemas/serializers | M | Medio (PII: revisar `numero_cuenta`) |
| TCH-PAR-10 | Tablas de control adicionales: FLUJO MANDATOS CANT/MONTO (vigentes/altas/bajas por entidad), RECHAZOS y ENT RECHAZOS por motivo, KPI | models/tch.py, etl_tch.py, routes/tch.py, front /tch | M | Bajo |
| TCH-PAR-11 | Actualizacion mensual robusta: sha256 y registro de archivos, mes desde contenido, rechazo de duplicados, upsert de ventana, pantalla de resultado y conciliacion | routes/tch.py, etl_tch.py, nueva tabla `tch_report_files`, front admin | M | Medio |
| TCH-PAR-12 | Core: upsert real de `core_payments` (DO UPDATE), periodo en pagos, crear `core_charges`/cuota para TCH, `client_external_id` | core_tch_etl.py, channel_consolidation.py, core.py | M | Medio |
| TCH-PAR-13 | Consolidacion TCH incremental (solo cambios) en lugar de 1,47 M filas por noche | channel_consolidation.py, sync_all.py | M | Medio |
| TCH-PAR-14 | ADR-001: RUT solo como external_id del canal; validar checksum, aislar no validos, tipo_persona real, no poblar `social_id` canonico para matching | channel_consolidation.py, core_materialization.py, client_match_detector.py, docs/data/tch.md | S-M | Medio |
| TCH-PAR-15 | Limpiar `tch_recaudacion_mensual` (futuros en cero, 2017-05/06 faltantes) y `cutoff` real | etl_tch.py | S | Bajo |
| TCH-PAR-16 | Rendimiento y memoria del ETL: leer cada hoja una sola vez (openpyxl read_only o pandas con usecols), correr fuera del proceso API | etl_tch.py, routes/tch.py | M | Medio |
| TCH-PAR-17 | Altas/bajas del dashboard: respaldo cuando `fecha_activacion` esta vacia (post jul-2025: primer cobro / entrega banco); explicar corte de la fuente | routes/tch.py `tch_summary` | S | Bajo |
| TCH-PAR-18 | Eliminar `codigo_respuesta` (siempre NULL) o derivarlo de Motivo; catalogar motivos | models/tch.py, etl_tch.py | S | Bajo |
| TCH-PAR-19 | Pruebas de paridad: Excel sintetico sin PII con 3 layouts (A, B-2022, sin VIGENTES-2023), nombres sin fecha, cuota entera/flotante, reintento; VAL-TCH-01 | tests/test_etl_tch.py, tests/fixtures | M | Bajo |
| TCH-PAR-20 | Documentacion: corregir docs/data/tch.md (dice 29 archivos y ~150 k transacciones; real 30 archivos / 1,47 M), hoja de ruta de carga | docs/data/tch.md, docs/integrations/tch.md | S | Bajo |

Orden sugerido: 01, 02, 05, 06, 15 (S, desbloquean la recarga) → decidir DEC-04 → 03, 04, 07 (recarga y conciliacion) → 08, 09, 10 → 11, 12, 13, 14, 16 → 17-20.

Nota de proceso: ninguna escritura en `crm`; la recarga (que hace DELETE de tablas tch_*) y las migraciones requieren al usuario por las reglas del handoff.
