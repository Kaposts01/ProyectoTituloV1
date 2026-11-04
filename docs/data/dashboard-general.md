# Resumen unificado de la jefatura: `GET /api/v1/dashboard/general` (UX-07)

> Sprint 5, rama `sprint-5/sync-confiable`. Código: `app/api/v1/routes/dashboard.py`, `app/services/dashboard_general.py`.
> Pruebas: `tests/test_dashboard_general.py` (datos sintéticos de los 4 canales, sin datos personales). Sin migraciones.
> Es un endpoint **nuevo y de solo lectura**: el dashboard actual (`GET /api/v1/staging/dashboard/general`) no se modifica.
> Las definiciones marcadas como **propuesta** están pendientes de confirmación del usuario (ver §4).

## 1. Petición

`GET /api/v1/dashboard/general?month=YYYY-MM&channels=virtualpos,toku,payku,tch`

| Parámetro | Detalle |
|---|---|
| `month` | `YYYY-MM` en hora de Chile. Por defecto, el mes actual (America/Santiago). Formato inválido: 422 `{"detail":{"code":"invalid_month","message":...}}` |
| `channels` | Lista separada por comas de `virtualpos`, `toku`, `payku`, `tch` (`virtualpos` suma las cuentas 1 y 2). Por defecto, todos. Un canal desconocido o la lista vacía: 422 `invalid_channel` |

**Permisos.** Exige `dashboard.view` (403 si falta). El filtro de canales se resuelve **en el servidor**: cada canal pedido exige además
`<canal>.dashboard.view` (`virtualpos.dashboard.view`, `toku.dashboard.view`, `payku.dashboard.view`, `tch.dashboard.view`); un canal sin permiso
**no aparece** (no se calcula, no figura en `channels`, en `ingreso_por_canal`, en `mrr.por_canal` ni en las series, y no suma en los totales).
No se informa cuáles se descartaron. Si no queda ningún canal, todos los KPIs vienen en `null`.

## 2. Respuesta (contrato JSON exacto)

Ejemplo real generado con datos sintéticos de las pruebas (ahora fijo = 2026-10-15). Las series se recortaron a 2 meses en este documento;
**en la respuesta real `series.months` y cada serie tienen 12 elementos**, terminando en `month`.

```json
{
  "month": "2026-10",
  "timezone": "America/Santiago",
  "generated_at": "2026-10-15T12:00:00-03:00",
  "is_current_month": true,
  "channels": ["virtualpos", "toku", "payku", "tch"],
  "kpis": {
    "socios_totales": {
      "valor": 8,
      "valor_mes_anterior": 9,
      "delta_vs_mes_anterior": -1,
      "delta_vs_mes_anterior_pct": -11.1,
      "meta": null,
      "estado_meta": "sin_meta",
      "unidad": "count",
      "socios_totales_nota": "suma por canal, no deduplicada",
      "socios_totales_unidad": "suscripciones"
    },
    "activaciones": {
      "valor": 3, "valor_mes_anterior": 1, "delta_vs_mes_anterior": 2, "delta_vs_mes_anterior_pct": 200.0,
      "meta": null, "estado_meta": "sin_meta", "unidad": "count"
    },
    "bajas": {
      "valor": 4, "valor_mes_anterior": 1, "delta_vs_mes_anterior": 3, "delta_vs_mes_anterior_pct": 300.0,
      "meta": null, "estado_meta": "sin_meta", "unidad": "count"
    },
    "crecimiento_neto": {
      "valor": -1, "valor_mes_anterior": 0, "delta_vs_mes_anterior": -1, "delta_vs_mes_anterior_pct": null,
      "meta": null, "estado_meta": "sin_meta", "unidad": "count"
    },
    "churn": {
      "valor": 44.4, "valor_mes_anterior": 11.1, "delta_vs_mes_anterior": 33.3, "delta_vs_mes_anterior_pct": 300.0,
      "meta": null, "estado_meta": "sin_meta", "unidad": "pct",
      "churn_definicion": "Propuesta pendiente de confirmación: bajas del mes ÷ socios al inicio del mes (cierre del mes anterior), en porcentaje y con la misma definición en todos los canales.",
      "churn_window_label": "mes calendario (hora de Chile): bajas del mes ÷ socios al cierre del mes anterior"
    },
    "ingreso_total": {
      "valor": 92000, "valor_mes_anterior": 75000, "delta_vs_mes_anterior": 17000, "delta_vs_mes_anterior_pct": 22.7,
      "meta": null, "estado_meta": "sin_meta", "unidad": "clp"
    },
    "ingreso_por_canal": {
      "virtualpos": {"valor": 15000, "valor_mes_anterior": 20000, "delta_vs_mes_anterior": -5000, "delta_vs_mes_anterior_pct": -25.0, "meta": null, "estado_meta": "sin_meta", "unidad": "clp"},
      "toku":       {"valor": 20000, "valor_mes_anterior": 15000, "delta_vs_mes_anterior": 5000, "delta_vs_mes_anterior_pct": 33.3, "meta": null, "estado_meta": "sin_meta", "unidad": "clp"},
      "payku":      {"valor": 7000, "valor_mes_anterior": null, "delta_vs_mes_anterior": null, "delta_vs_mes_anterior_pct": null, "meta": null, "estado_meta": "sin_meta", "unidad": "clp"},
      "tch":        {"valor": 50000, "valor_mes_anterior": 40000, "delta_vs_mes_anterior": 10000, "delta_vs_mes_anterior_pct": 25.0, "meta": null, "estado_meta": "sin_meta", "unidad": "clp"}
    },
    "acumulado_anio": {
      "valor": 168000, "valor_mes_anterior": 76000, "delta_vs_mes_anterior": 92000, "delta_vs_mes_anterior_pct": 121.1,
      "meta": null, "estado_meta": "sin_meta", "unidad": "clp"
    },
    "cobrabilidad": {
      "valor": 66.7, "valor_mes_anterior": 78.6, "delta_vs_mes_anterior": -11.9, "delta_vs_mes_anterior_pct": -15.1,
      "meta": null, "estado_meta": "sin_meta", "unidad": "pct"
    },
    "no_cobrado": {
      "valor": 30000, "valor_mes_anterior": 11000, "delta_vs_mes_anterior": 19000, "delta_vs_mes_anterior_pct": 172.7,
      "meta": null, "estado_meta": "sin_meta", "unidad": "clp"
    },
    "por_cobrar": {
      "valor": 10000, "valor_mes_anterior": 0, "delta_vs_mes_anterior": 10000, "delta_vs_mes_anterior_pct": null,
      "meta": null, "estado_meta": "sin_meta", "unidad": "clp"
    },
    "mrr": {
      "valor": 90000, "valor_mes_anterior": null, "delta_vs_mes_anterior": null, "delta_vs_mes_anterior_pct": null,
      "meta": null, "estado_meta": "sin_meta", "unidad": "clp",
      "por_canal": {"virtualpos": 25000, "toku": 8000, "payku": 7000, "tch": 50000}
    },
    "arpu": {
      "valor": 12857, "valor_mes_anterior": null, "delta_vs_mes_anterior": null, "delta_vs_mes_anterior_pct": null,
      "meta": null, "estado_meta": "sin_meta", "unidad": "clp"
    }
  },
  "series": {
    "months": ["2026-09", "2026-10"],
    "ingreso_por_canal": [
      {"month": "2026-09", "total": 75000, "canales": {"virtualpos": 20000, "toku": 15000, "payku": null, "tch": 40000}},
      {"month": "2026-10", "total": 92000, "canales": {"virtualpos": 15000, "toku": 20000, "payku": 7000, "tch": 50000}}
    ],
    "activaciones": [{"month": "2026-09", "valor": 1}, {"month": "2026-10", "valor": 3}],
    "bajas": [{"month": "2026-09", "valor": 1}, {"month": "2026-10", "valor": 4}],
    "socios_totales": [{"month": "2026-09", "valor": 9}, {"month": "2026-10", "valor": 8}]
  },
  "calidad_datos": {"altas_sin_fecha": 0, "bajas_sin_fecha": 0}
}
```

### Campos de primer nivel

| Campo | Tipo | Detalle |
|---|---|---|
| `month` | string `YYYY-MM` | Mes pedido (o el actual). |
| `timezone` | string | Siempre `America/Santiago`. |
| `generated_at` | string ISO 8601 | Momento del cálculo (hora de Chile). |
| `is_current_month` | boolean | `month` es el mes en curso. Solo entonces `mrr` y `arpu` tienen valor. |
| `channels` | string[] | Canales efectivos (los pedidos y permitidos), en orden fijo `virtualpos, toku, payku, tch`. |
| `kpis` | objeto | Ver abajo. |
| `series` | objeto | Ver abajo. |
| `calidad_datos` | objeto | `altas_sin_fecha`: suscripciones sin fecha de alta válida (no entran a socios, altas ni bajas). `bajas_sin_fecha`: suscripciones en estado de baja sin fecha de baja válida (o anterior a su alta); no se pueden ubicar en un mes. Enteros ≥ 0 sobre los canales efectivos. |

### Objeto KPI (todos los de `kpis` y cada elemento de `ingreso_por_canal`)

| Campo | Tipo | Detalle |
|---|---|---|
| `valor` | número o `null` | Valor del mes. **`null` = sin dato** (el front muestra «—»); nunca se inventa un 0. |
| `valor_mes_anterior` | número o `null` | El mismo KPI para el mes calendario anterior. |
| `delta_vs_mes_anterior` | número o `null` | `valor - valor_mes_anterior`. En KPI de `unidad: "pct"` son **puntos porcentuales**. `null` si falta alguno de los dos. |
| `delta_vs_mes_anterior_pct` | número o `null` | Variación relativa en % (1 decimal) = `delta / abs(valor_mes_anterior)`. `null` si falta un valor o el anterior es 0. |
| `meta` | `null` | Siempre `null` por ahora (no existe tabla de metas; D2 pendiente del usuario). |
| `estado_meta` | string | Siempre `"sin_meta"` por ahora. Valores futuros previstos: `en_meta`, `cerca`, `lejos`. |
| `unidad` | string | `count` (enteros), `clp` (pesos) o `pct` (porcentaje con 1 decimal). |

KPIs con campos extra: `socios_totales` (`socios_totales_nota`, `socios_totales_unidad`), `churn` (`churn_definicion`, `churn_window_label`) y `mrr`
(`por_canal`: objeto canal → número o `null`).

### `kpis`

| Clave | Definición |
|---|---|
| `socios_totales` | Suscripciones activas **al cierre del mes** = altas con fecha ≤ fin de mes − bajas con fecha ≤ fin de mes. **Suma por canal, NO deduplicada** y sin afirmar un total único de socios: `socios_totales_nota` = «suma por canal, no deduplicada» hasta que exista el trabajo sobre Core (ADR-001). La unidad es la suscripción (`socios_totales_unidad: "suscripciones"`), no el RUT. |
| `activaciones` | Altas del mes: suscripciones cuya fecha de alta cae en el mes (`suscription_date`; TCH la fecha de alta efectiva de TCH-PAR-17: `fecha_activacion`, si falta `fecha_primer_cobro` y si falta `fecha_entrega_banco`, la misma del dashboard de TCH). Se excluyen las que nunca fueron alta: VirtualPOS `SUSCRIPCION_FALLIDA`, Payku `register` (inscripción de tarjeta sin completar) y TCH `RECHAZADA`. Toku sin fila en el reporte de Productos no tiene alta (d141: el `anchor` de la API es el próximo cobro) y cuenta en `calidad_datos.altas_sin_fecha`. |
| `bajas` | Bajas del mes: suscripciones en **estado de baja del canal** (`BAJA_STATES` de `app/services/status_history.py`; TCH además `ELIMINADA`) con **fecha de baja** en el mes (`canceled_at`; TCH `fecha_eliminacion`) y alta válida anterior o igual. No depende de `status_change_events` (su historia empieza al aplicar la migración 0042). |
| `crecimiento_neto` | `activaciones - bajas`. |
| `churn` | **Propuesta**: `bajas del mes ÷ socios al inicio del mes × 100` (socios al cierre del mes anterior), 1 decimal, misma fórmula para los 4 canales. `null` sin socios al inicio. El resumen la calcula para el mes elegido; los dashboards de canal (`app/services/channel_churn.py`) la toman del **último mes cerrado con dato** (hora de Chile), porque el mes en curso casi siempre da 0 % los primeros días, y su `churn_window_label` nombra ese mes (L6-DASH; sin claves nuevas en el JSON). |
| `ingreso_total` | Recaudado en el mes = suma del monto de los **cobros pagados** con fecha de cobro en el mes y ≤ hoy (VirtualPOS y Toku desde `charges`; Payku desde `payments`, porque no tiene cargos y cada transacción es un intento de cobro; TCH desde la recaudación mensual oficial o, si no hay controles, desde las transacciones aceptadas). Suma de los canales efectivos. |
| `ingreso_por_canal` | Objeto canal → KPI (mismo cálculo por canal). Solo canales efectivos. |
| `acumulado_anio` | Suma del `ingreso_total` de enero al mes pedido (mismo año). Su `valor_mes_anterior` es el acumulado a fin del mes anterior (si `month` es enero, el del año anterior). |
| `cobrabilidad` | `pagados ÷ (pagados + rechazados) × 100` con la **definición única** de `app/services/charge_stats.py` (`charge_rejection_stats`): cargos con fecha ≤ hoy (Chile), sin cancelados/expirados/anulados ni pendientes; **sin cobros futuros**. `null` sin denominador. TCH aporta los conteos de su recaudación mensual. |
| `no_cobrado` | Monto de los cobros **rechazados** del mes (fecha ≤ hoy; sin futuros). Toku no marca la factura como rechazada: una factura `UNPAID`/`PARTIALLY_PAID` con fecha ≤ hoy cuenta como rechazada (no cobrada) y, con fecha futura, como pendiente. |
| `por_cobrar` | Monto de los cobros **pendientes o procesando** con fecha de cobro dentro del mes (incluye los vencidos y los programados más adelante en el mes). TCH no aporta (sin cobros programados). |
| `mrr` | **Solo mes en curso** (es una foto del estado actual; no hay historia): suma de los MRR de cada canal con las definiciones vigentes de sus dashboards: VirtualPOS = `monto_vigente` de las suscripciones `ACTIVA`; Toku = monto de las suscripciones activas con medio de pago `chargeable`; Payku = monto de la última transacción exitosa de cada suscripción activa; TCH = `equivalente_pesos` de las `VIGENTE`. `por_canal` lo desglosa (`null` si el canal no tiene suscripciones activas). Meses pasados o futuros: `null`. |
| `arpu` | `mrr ÷ clientes activos` (suma de los clientes activos de cada canal con su definición vigente: RUT distinto de las activas en VirtualPOS y Payku, cliente distinto en Toku, RUT distinto de las vigentes en TCH; si falta el dato, el número de suscripciones). Mismo criterio de mes en curso que `mrr`. |

### `series` (12 meses terminando en `month`, orden ascendente)

| Clave | Forma |
|---|---|
| `months` | `["2025-11", ..., "2026-10"]` (12 elementos). |
| `ingreso_por_canal` | `[{"month", "total": número o null, "canales": {"virtualpos": número o null, ...}}]`, listo para un gráfico apilado. Solo canales efectivos. |
| `activaciones` | `[{"month", "valor": número o null}]` |
| `bajas` | `[{"month", "valor": número o null}]` |
| `socios_totales` | `[{"month", "valor": número o null}]` (al cierre de cada mes; suma por canal, no deduplicada). |

### Reglas de `null`
- Un mes **posterior al mes actual** (Chile) devuelve `null` en todo (KPIs y puntos de las series).
- Socios, activaciones, bajas y churn son `null` mientras ningún canal efectivo tenga una alta con fecha ≤ fin de ese mes (antes de la primera alta no hay historia).
- `ingreso`, `no_cobrado` y `por_cobrar` son `null` si ningún canal efectivo tuvo cobros en el mes (en un mes con cobros, un 0 es un 0 real).
- Un canal sin cobros en el mes viene `null` en `ingreso_por_canal` aunque otros canales tengan datos.
- Un mes sin ningún dato devuelve todo `null`, no ceros. Una base vacía en el mes actual también.

## 3. Diferencias con el dashboard actual para los mismos datos

Medidas con los datos sintéticos de las pruebas (ahora = 2026-10-15). Ninguna es un error: son definiciones distintas.

| Tema | Dashboard actual | Este endpoint | Motivo |
|---|---|---|---|
| Suscripciones activas / socios | `subscriptions.active` = 8 (activas **hoy**; Toku exige medio `chargeable`) | `socios_totales` = 8 | Coinciden en el mes actual con estos datos; en datos reales pueden diferir porque el endpoint nuevo se calcula por fechas de alta/baja (histórico) y no aplica el filtro `chargeable` de Toku (no es reconstruible hacia atrás). |
| Churn | 50,0 % = bajas del mes ÷ activas **hoy** (4/8) | 44,4 % = bajas del mes ÷ socios **al inicio del mes** (4/9) | Denominador distinto (definición unificada propuesta). |
| Altas del mes | 4 (VirtualPOS 3 + TCH 1) | 3 | El actual cuenta la suscripción `SUSCRIPCION_FALLIDA`; el nuevo la excluye. |
| Bajas del mes | 4 | 4 | Coinciden. El nuevo exige además estado de baja del canal y alta válida anterior. |
| Rechazo / cobrabilidad | Tasa **acumulada de todos los meses** (10 de 36) | Cobrabilidad **del mes** (14 de 21 = 66,7 %) | Misma definición (`charge_stats`), distinta ventana. |
| Cobros futuros | Excluidos de la tasa y de `debts_monthly` | Excluidos de cobrabilidad, ingreso y no cobrado (el rechazado de 7.000 con fecha 10-28 no cuenta) | Igual criterio. |
| Pendientes | `pending_payments` = 1 (cuenta, solo fecha ≤ hoy) | `por_cobrar` = 10.000 (monto, incluye el programado el 10-25 dentro del mes) | Cuenta frente a monto, y el nuevo incluye lo programado dentro del mes. |
| Rechazado en VirtualPOS | `debts_monthly` clasifica como «rechazada» todo lo que no es pagado (7.000 = 3.000 rechazado + 4.000 pendiente; UI-28) | `no_cobrado` = 3.000 | El nuevo usa solo el estado rechazado. |
| Ingreso | `transactions_monthly`: **pagos** aceptados (`payments`) | `ingreso_total`: **cobros** pagados (`charges`) | En datos reales ambos pueden diferir (un cobro pagado sin pago registrado, o viceversa). La instrucción fue «recaudado = cobros pagados». Validar con el usuario si prefiere pagos. |

## 4. Definiciones propuestas pendientes de confirmación del usuario

1. **Churn unificado (DEC-37, propuesta):** `bajas del mes ÷ socios al inicio del mes`, mensual y calendario, igual para los 4 canales. Hoy cada canal usa
   una ventana distinta (VirtualPOS promedia 3 meses; Toku y Payku acumulado; TCH promedio histórico; el general, bajas del mes ÷ activas hoy). Alternativas:
   (A, recomendada) la propuesta; (B) tasa móvil de 3 meses; (C) mantener una definición por canal y no sumarlas. Mientras no se confirme, `churn_definicion`
   dice «Propuesta pendiente de confirmación». Decisión D20 del usuario: el churn se muestra como tarjeta con meta (la meta sigue en `null`).
2. **Socios no deduplicados:** `socios_totales` es la **suma por canal de suscripciones activas**. Un mismo socio con suscripciones en dos canales, o con dos
   suscripciones en el mismo canal, cuenta más de una vez. No se afirma un total único de socios hasta que exista la identidad centralizada sobre Core
   (ADR-001, `docs/designs/reconciliacion-identidad-socios.md`). Alternativa futura: contar identidades distintas sobre Core.
3. **Unidad del «socio»:** la suscripción (no el RUT). Mantiene la identidad `socios(t) = socios(t-1) + altas − bajas`.
4. **Ingreso = cobros pagados** (no pagos) y **por cobrar incluye lo programado dentro del mes** (ver §3).
5. **MRR y ARPU solo para el mes en curso** (no hay historia del MRR; un histórico exigiría guardar fotos mensuales: DEC-35 C).

### Lo que falta para completar los 14 KPIs de la captura de inspiración
- **Metas** (chip «en meta/lejos», diferencia vs meta, ritmo meta, proyección, pestaña Plan 2030): no existe tabla de metas (D2 pendiente). Todos los KPIs devuelven
  `meta: null` y `estado_meta: "sin_meta"`; al existir las metas basta con rellenar esos campos sin cambiar el contrato (requerirá una migración).
- **Etas** y **Donación individual**: el CRM solo cubre el recurrente de los 4 canales; no hay fuente de datos. Omitidos (no se inventan).
- **Histórico de MRR** y **deduplicación de socios entre canales**: ver puntos 5 y 2.
- **Cobertura de TCH:** viene de reportes Excel semanales; el front debería rotular «dato al <fecha>». Payku tiene cobertura no certificada.

## 5. Rendimiento

Consultas **agregadas en SQL** (no se cargan filas): histogramas de altas y bajas por canal y mes, una consulta de cobros agrupados por día y estado dentro de la
ventana, y la recaudación mensual de TCH. Solo el MRR del mes en curso lee las suscripciones activas (misma forma que los dashboards de canal). Sin caché.
Medido en la base de pruebas con 20.000 suscripciones y 120.000 cobros sintéticos: **0,57 s** para el mes en curso (incluye MRR/ARPU) y **0,25 s** para un mes pasado;
el cálculo del dashboard general actual con esos mismos datos tardó 0,58 s. Los cobros no tienen índice por fecha (la columna es texto): con volúmenes mucho mayores
convendría un índice sobre `substring(charge_date, 1, 7)` o materializar el resumen (decisión futura, no necesaria hoy).
