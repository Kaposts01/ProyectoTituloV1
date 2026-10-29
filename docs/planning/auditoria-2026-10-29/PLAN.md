# Plan consolidado: datos confiables, al día y gestionables (auditoría del 2026-10-29)

Resumen de 10 informes de solo lectura (esta carpeta). El estado de cada tarea vive en `docs/tasks.md` (§3.7); aquí está el razonamiento, el orden y las dependencias. Rama de trabajo: `sprint-5/sync-confiable`.

## 1. Objetivo
Que el CRM tenga, tras la carga histórica y la sincronización diaria, la misma cantidad, calidad y tipo de datos que los reportes de cada portal (fuente de verdad), siempre al día; con historial de cambios de estado, glosas de rechazo, baja y cambio de monto desde el CRM, y una vista unificada con los KPIs de la jefatura.

## 2. Estado medido (paridad contra reportes)

| Canal | Cantidad | Calidad / campos | Hueco principal |
|---|---|---|---|
| VirtualPOS | Idéntica (86.541 cobros, 9.005 suscripciones, mes por mes) | Glosa 0 %, vínculo pago-cobro 0 %, medio de pago por cobro no existe, 22 % sin últimos 4 | Glosa y vínculo; cobros futuros distorsionan KPIs |
| Toku | Cuadra hasta jul-2026 (±1–3 % por huso) | Fechas de alta/baja erróneas, estado de suscripción vacío, 157 eliminadas ausentes | Importador de reportes nunca ejecutado (0 filas); glosa no proyectada |
| Payku | Cuotas exitosas cuadran 74 de 74 meses | Rechazos sin glosa; fecha de cancelación 21 % (56 % con logs) | Detalle de transacción no consultado; donaciones puntuales fuera |
| TCH | **No cuadra**: 1,47 M en CRM contra 1,0 M del control | Lee `Periodo` en vez de `Cuota Mes`; duplicados `12`/`12.0`; carga mensual reinserta 12 meses; faltan meses 05-06 y 2023; monto NULL | ETL y recarga completa |

## 3. Hallazgos operativos urgentes
1. VirtualPOS 2 y Payku sin sincronizar desde el 27-28 oct (variables de entorno tras el commit `25eafac`). Código corregido en `b6a590c`; **el usuario debe reiniciar el backend 8000 y revisar su `.env`**.
2. No hay historial de estados ni resumen diario de cambios.
3. El sync nocturno dura ~2,8 h: más del 99 % es trabajo redundante (Toku transacciones sin ventana 47 %, TCH 13 %, VP triple consolidación).
4. El ETL Core no está programado (Toku y Payku quedaron al 21-oct).

## 4. Olas de trabajo

Restricciones: una sola sesión de pytest a la vez (todas recrean `crm_test`); ningún agente corre Alembic ni escribe en `crm`; las migraciones y recargas en `crm` las ejecuta el usuario; `git add` por ruta; sin push ni PR.

**Ola 0 (hecha):** SYNC-D-09 / VP-PAR-01 / PK-PAR-01, commit `b6a590c`.

**Ola 1: código sin migración (secuencial por agente).**
- 1A Glosa: RJ-02, RJ-03, RJ-05, RJ-01 (en curso).
- 1B TCH: TCH-PAR-01, 02, 05, 06, 15 y 18.
- 1C Sync rápido: SYNC-O-11 (= SYNC-D-06), SYNC-O-03, SYNC-O-04, SYNC-O-01, PK-PAR-02/03/08, VP-PAR-10 y 05, TK-PAR-08.
- 1D Seguridad de bajas: MGT-01, 02, 05.

**Ola 2: migración que aplica el usuario.** SYNC-D-01/02/03 (`status_change_events`, baseline), RJ-12 (tabla de rechazos), SYNC-O-08 (`sync_cursors`, `tch_file_loads`), RT-04 (`webhook_events`).

**Ola 3: importadores y recargas.** VP-PAR-02 / RJ-04 (reportes PAT), TK-19 y TK-PAR-02 (reportes de Toku, requiere pepper), recarga TCH (TCH-PAR-07, la ejecuta el usuario), ventanas de fecha (SYNC-O-02/05/06, tras pruebas en sandbox), niveles caliente/tibia/fría (SYNC-O-09).

**Ola 4: tiempo real, gestión y vista unificada.** Resumen diario y SSE (SYNC-D-04, RT-11/12), reconciliación dirigida (RT-06), webhooks Toku (RT-03 a RT-08), cascada de baja (MGT-03 a MGT-17), menú y dashboard unificados con KPIs de la jefatura (UX-00 a UX-16).

## 5. Decisiones que necesita del usuario (con recomendación)

| # | Decisión | Recomendación |
|---|---|---|
| D1 | Diseño: sidebar teal de `DESIGN.md` o azul marino de la captura | Mantener teal; marino, cian y magenta solo en gráficos y encabezado del Resumen |
| D2 | Origen de Etas y Donación individual, y quién entrega las metas 2026-2030 | Del usuario; sin fuente hoy |
| D3 | Tabla única de rechazos o columnas por canal | Tabla única (`payment_rejection_details`) |
| D4 | Materializar ~29 mil FAILED de Toku como `core_payments` | No; solo `core_charges` |
| D5 | Autorizar 3 GET de lectura en producción de VP y 1 de Payku para la glosa | Sí, con tope y sin imprimir datos |
| D6 | Fuente histórica de glosa de VP | Reportes PAT (cubren 100 % de rechazos) |
| D7 | Enganche del historial de estados | Opción A (en `_upsert_centralized`) |
| D8 | Exposición pública de webhooks | B (receptor mínimo externo) como puente, o A con allowlist; DEC-11 |
| D9 | Tiempo real hacia la interfaz | SSE con respaldo de polling |
| D10 | Cadencia caliente (3 o 6 h) y ventana nocturna | 3 h entre 07:00 y 22:00 |
| D11 | Scheduler | Worker separado (lock advisory ya) |
| D12 | Baja: quién solicita y aprueba; medios de pago; Toku con PAUSED o DELETE | Jefatura solicita, admin o jefatura aprueban; Toku PAUSED/`end_date` |
| D13 | DEC-04 de TCH | Clave (ficha, período, cuota) con último estado |
| D14 | Donaciones puntuales de Payku en el CRM | Decidir con la jefatura (afecta MRR) |
| D15 | Alertas: canal y destinatarios | Correo a jefatura |
| D16 | URL de VirtualPOS 2 igual a la de la cuenta 1 | Confirmar |

### 5.1 Decisiones resueltas por el usuario (bandeja, 2026-10-29)

| # | Resolución | Consecuencia |
|---|---|---|
| D1 | Menú azul marino como la captura (no la recomendada) | Actualizar `DESIGN.md` (sidebar, tokens, contrastes) antes de UX-05; pasa por /design-consultation |
| D2 | Fuera del dashboard por ahora; el usuario tiene las bases y las entregará | Diseñar tabla de metas y carga simple cuando las entregue |
| D3 | Tabla única `payment_rejection_details` | Migración (RJ-12), la aplica el usuario |
| D4 | Materializar los FAILED de Toku como `core_payments` (no la recomendada) | Tarea nueva RJ-15: backfill con cuidado en KPIs (cobrabilidad, rechazos); la Ola 1A solo actualizó `core_charges` |
| D5 | Autorizadas 4 lecturas GET en producción (3 VirtualPOS, 1 Payku) | Ejecutadas con tope; informe `prod_reads_glosa` |
| D6 | Importador de reportes PAT de VirtualPOS | RJ-04 / VP-PAR-02 |
| D7 | Historial de estados en `_upsert_centralized` | SYNC-D-01/02/03; migración, la aplica el usuario |
| D8 | Túnel nombrado con dominio fijo (solo `/api/v1/webhooks/*`) como puente hasta migrar a hosting | Crítica: no se expone nada sin una confirmación adicional en el momento; depende de SYNC-D-01/02, RT-04 y RT-08 |
| D9 | SSE con polling de respaldo | RT-11/12 |
| D10 | Caliente cada 3 h (07:00-22:00); fría el domingo de madrugada | SYNC-O-09 |
| D11 | Lock advisory ya; worker separado como destino | SYNC-O-11 y SYNC-O-12 |
| D12 | Jefatura solicita; admin o jefatura aprueban; Toku con PAUSED/`end_date`; ejecutivo solo lee | MGT-07, MGT-16 |
| D13 | Clave (ficha, período, cuota) con el último estado | TCH-PAR-03/04/07; la recarga la ejecuta el usuario |
| D14 | Donaciones puntuales de Payku fuera por ahora | PK-PAR-09 diferida |
| D15 | Alertas por correo a esteban.b@techo.org | SYNC-D-08; requiere configurar envío (secretos solo en `.env`) |
| D16 | VirtualPOS 2 usa el mismo host que la cuenta 1 | Se conserva el respaldo de URL |
| D17 | Texto del `-11` según el reporte del portal («Excede límite de reintentos de rechazo») | Cambiar catálogo y el test que lo fija (próxima tanda) |
| D18 | `docs/Reportes_*/` al `.gitignore` | Hecho |

## 6. Acciones del usuario (no delegables)
Reiniciar backend 8000; revisar `.env` (nombres de variables); definir `TOKU_REPORT_HASH_PEPPER`; exportar reporte de Deudas e Intentos de Toku; reexportar la cartera TCH de 2023; aplicar migraciones y recargas en `crm` con respaldo previo; correr `seed_roles.py`.

## 7. Incidentes de privacidad de esta auditoría (regla 11)
- Un agente de VirtualPOS vio direcciones en texto libre al perfilar un CSV (no copiadas).
- Un agente de TCH imprimió una vez en consola una fila de datos de un socio (no escrita en repo ni documentos; intermedios regenerados).
Corrección: los agentes de paridad deben leer encabezados con una función que nunca imprima filas.
