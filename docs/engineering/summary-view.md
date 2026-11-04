# Resumen unificado (frontend)

Pantalla «Resumen» en `/central/resumen`. Consume únicamente `GET /api/v1/dashboard/general` (contrato en `docs/data/dashboard-general.md`). Código en `frontend/src/features/summary/`.

## Estructura

| Archivo | Responsabilidad |
| --- | --- |
| `summaryTypes.ts` | Tipos internos, en inglés |
| `summaryAdapter.ts` | Único módulo que conoce las claves en español del endpoint |
| `summaryApi.ts` | `fetchSummary` sobre `getJson` de `api.ts`; errores 422 en español |
| `summaryFixtures.ts` | Datos sintéticos para pruebas, sin datos personales |
| `useSummary.ts` | Estado de carga, error, reintento, mes y canales |
| `SummaryView.tsx` | Composición de la pantalla |
| `SummaryControls.tsx` | Selector de mes y filtro de canales (solo los que devuelve el servidor) |
| `SummaryKpiGrid.tsx` | 12 tarjetas con `KpiCard` v2 y `ChurnKpiCard` |
| `SummaryCharts.tsx` | Gráficos con `ChannelChart` y `ChartRangeSelector` |
| `SummaryHealth.tsx` | Salud de canal (`GET /api/v1/sync-runs/health`) |
| `summaryFormat.ts`, `summaryChartData.ts` | Formato y datos de gráficos |

Además: `components/healthLabels.ts` (textos de salud compartidos con el menú) y la ampliación de `ChannelChart` (`kind="area"`, `overlayLine`).

## El adaptador (decisión D33)

Mapeo principal de claves: `socios_totales` a `totalMembers`, `valor_mes_anterior` a `previousMonthValue`, `activaciones` a `activations`, `bajas` a `cancellations`, `crecimiento_neto` a `netGrowth`, `ingreso_total` a `totalRevenue`, `acumulado_anio` a `yearToDate`, `cobrabilidad` a `collectability`, `no_cobrado` a `uncollected`, `por_cobrar` a `receivable`, y `estado_meta "sin_meta"` a `goalStatus "none"`.

Cuando el backend renombre las claves, solo cambian `summaryAdapter.ts` y sus fixtures.

Reglas verificadas por pruebas:
- `null` se queda en `null`, nunca se convierte en 0 (la pantalla muestra «—»).
- Un canal sin permiso no aparece en ninguna parte.
- Un estado de meta desconocido se trata como «sin meta».
- Un mes sin datos deja todo en `null` y `hasAnyData` es falso.

## Pantalla

- Selector de mes («Mes actual») y filtro de canales; pestañas «Últimos 12 meses / Año / Todo».
- Tarjetas con variación contra el mes anterior y el chip «sin meta» (no hay metas: D2 pendiente). Ingreso total va destacada. Socios totales lleva la nota «Suma por canal, no deduplicada (unidad: suscripciones)». MRR y ARPU muestran «—» y «Solo disponible para el mes en curso» cuando son `null`.
- Churn con `ChurnKpiCard` (D20) y su definición como ayuda normal DENTRO de la tarjeta (prop `help`): «Bajas del mes ÷ socios al inicio del mes» (D31 confirmada; el contrato la dice «socios al cierre del mes anterior», que es lo mismo).
- Gráficos desde `series` (12 meses): ingreso por canal apilado, socios totales como área, activaciones y bajas con crecimiento neto. Cada uno con «Ver datos». El eje Y se ensancha según la etiqueta más larga (no recorta «$200.000») y el eje X usa `interval="preserveStartEnd"` con `minTickGap` de 24 px para que los meses no se superpongan.
- TCH se rotula «Dato al <fecha>», porque viene de Excel.
- Estados de carga (esqueleto), error con «Reintentar» y mes sin datos (con «Ver el mes anterior»).

## Rutas

| Ruta | Contenido |
| --- | --- |
| `/central/resumen` | Resumen unificado (nuevo) |
| `/central/resumen-clasico` | Retirada en UX-15 (2026-11-04): redirige a `/central/resumen` reemplazando el historial |

UX-15 (d110 a, revisión visual aprobada en d148) retiró la vista anterior y su código (`GeneralSummaryContent`, `GeneralKpis`, `generalKpiData`, `applyChargeFilter`, `seriesStackedChart` y el estado de modo, año y filtros de `useGeneralDashboard`). La prueba `etl.i18n` cubría solo sus tarjetas por canal y se eliminó; `general.characterization` conserva el panel ETL sobre Socios. La vista inicial no pide `staging/summary` ni `staging/dashboard/general` (hallazgo 5 de `appcore-extraction.md`). Los endpoints del backend siguen disponibles.

## Qué falta

- Metas (D2, UX-14): chips «en meta», barra de avance, ritmo, proyección y Plan 2030. `ChannelChart` ya tiene `kind="cumulative"` para cuando existan.
- Etas y Donación individual (sin fuente de datos).
- Histórico de MRR (UX-13).
- Deduplicación entre canales (ADR-001).
- «Año» y «Todo» recortan solo lo recibido: el endpoint entrega 12 meses.
- Tarjetas de ingreso por canal (el dato se adapta pero solo se usa en gráficos y tablas).
- Retirar la vista clásica (UX-15) y capturas visuales (UX-16).
