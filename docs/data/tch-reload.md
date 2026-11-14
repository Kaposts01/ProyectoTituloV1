# Recarga completa de TCH (procedimiento para el usuario)

Esta recarga reconstruye las tablas `tch_*` desde los reportes Excel con la clave estable de cuotas (D13). La ejecuta
el usuario sobre `crm`, con respaldo previo. Ningun agente corre Alembic ni la recarga.

## Que cambia (TCH-PAR-03, 04, 07, 09)

- Un cargo se identifica por `(ficha, periodo real, cuota)` y guarda el ULTIMO estado ("el ultimo reporte gana"). Una
  cuota rechazada y luego aceptada es UNA fila; el rechazo previo queda en `rechazo_previo`, `rechazo_previo_motivo` y
  `rechazo_previo_en`.
- `tch_transacciones.origen` separa `cargo` (hojas CARGOS, con fecha) de `historial` (estado mensual sin fecha). El
  historial de mandatos RECHAZADOS (que nunca cobraron) ya no se carga como cobro rechazado. Si una cuota esta en ambos
  origenes, es una sola fila y el cargo manda.
- El periodo sale de "Cuota Mes", la cuota es entera y se cargan monto y moneda vigentes.
- La recarga es transaccional y se concilia contra el control oficial (`tch_recaudacion_mensual`) antes de confirmar.

## Efecto esperado

| Medida | Antes | Despues |
|---|---|---|
| Filas de `tch_transacciones` | 1,47 M | cercano a 1,0 M (los intentos del control: 1.006.528 entre 2017-12 y 2026-09, mas lo que el historial aporte fuera de ese rango) |
| Fichas VIGENTES | 8.788 | cercano a 8.401 (se eliminan las 387 fichas ausentes del ultimo reporte) |
| Filas con `periodo` NULL | 108.585 | 0 |
| Monto de suscripcion | NULL en todas | cargado desde "Monto Vigente"; moneda en `moneda` |

El ano 2023 queda por debajo del control porque la hoja VIGENTES de Dic 2023 no trae cartera. Para que la conciliacion
no falle por eso, use `--exclude-months` con los meses de 2023 (se informan pero no cuentan) o consiga el archivo
reexportado.

## Pasos, en orden

1. **Respaldo.** `pg_dump -h localhost -p 5433 -U <usuario> -Fc -f respaldo_crm_antes_tch.dump crm` y verifique que el
   archivo existe y pesa algo razonable.
2. **Detenga otras cargas.** Que no haya sincronizacion ni importacion TCH en curso. El script toma el candado de
   `etl_runs`; si hay una corrida activa termina con codigo 2.
3. **Migraciones 0042 a 0048.** `alembic upgrade head` (solo agregan columnas y tablas nulas; no reescriben datos). Compruebe
   `alembic heads` = un solo head.
4. **Dry-run** (no cambia nada; reconstruye en una transaccion y la revierte):

   ```powershell
   $env:PYTHONPATH='.'
   .venv\Scripts\python.exe scripts\etl_tch.py --mode full --folder "C:\Users\Usuario\Downloads\Proyectos\CRM_reportes\TCH" `
     --exclude-months 2023-01,2023-02,2023-03,2023-04,2023-05,2023-06,2023-07,2023-08,2023-09,2023-10,2023-11,2023-12
   ```

   Imprime por mes las cuentas aceptadas/rechazadas de la base reconstruida frente al control y los meses que no
   cuadran. Umbrales por defecto: 0,5 % por mes y 0,1 % total (`--tolerance-month`, `--tolerance-total`). Si hay meses
   en `FALLA`, no continue: revise primero.
5. **Apply** (solo si el dry-run cuadra). Exige el nombre exacto de la base:

   ```powershell
   .venv\Scripts\python.exe scripts\etl_tch.py --mode full --folder "C:\Users\Usuario\Downloads\Proyectos\CRM_reportes\TCH" `
     --exclude-months <los mismos> --apply --confirm-database crm
   ```

   Todo o nada: si la conciliacion no cuadra se hace ROLLBACK y la base queda como estaba (codigo de salida 3).
6. **ETL Core de TCH** (re-materializa clientes, atributos, suscripciones, cuotas `core_charges` y pagos ligados a su
   cuota; elimina los pagos y cobros con la clave antigua; retira los atributos `rut` sin verificador valido):
   `POST /api/v1/etl/core/...` para TCH o `run_tch_core_etl`, y la consolidacion de `charges`. La recarga ya deja un
   `source_records` por fila `tch_*` (SYNC-D-16), asi que la consolidacion llena `source_record_id`. Sin recarga, el
   backfill es `scripts\etl_tch.py --backfill-source-records` (dry-run) y luego con `--apply --confirm-database crm`.
7. **Verificacion.** `python scripts/diagnostics/parity_check.py --channel tch` (solo lectura): los conteos por mes de
   `tch_transacciones` deben coincidir con el control. Revise tambien que las fichas VIGENTES sean ~8.401.

## Fecha de ingreso del mandato (fix/fechas-alta-tch-vp)

El ETL ahora carga la columna «Ingreso» (grupo `ANTECEDENTES Y ESTADO MANDATOS`, rotulo exacto `Ingreso`) en
`tch_suscripciones.fecha_ingreso`, que estaba vacia en todas las fichas. Es el ultimo respaldo de la fecha de alta
(activacion -> primer cobro -> entrega al banco -> ingreso): solo da fecha a las ~433 fichas que hoy no tienen ninguna,
sin mover de mes las altas que ya la tenian. Tambien reduce las «bajas sin fecha» cuyo problema era la falta de alta.

**Hay que recargar TCH para poblar `fecha_ingreso`**: hagalo en la ventana OPS-11 (ficha d209), con los pasos de
arriba. No hace falta migracion (la columna ya existe). Despues de la recarga, revise en el dashboard general que
`calidad_datos.altas_sin_fecha` (TCH) baje y mire `calidad_datos.bajas_antes_del_alta`: son bajas con fecha anterior
al alta (38 al diagnostico), marcadas para revision y no corregidas.

Bajas sin fecha: el reporte solo trae «Fecha Eliminado» (ya cargada en `fecha_eliminacion`). Las bajas implicitas
(fichas que desaparecen del ultimo reporte) no tienen fecha en ninguna columna del IG; seguiran contando en
`bajas_sin_fecha` salvo que se decida otra regla (p. ej. el periodo del primer reporte donde la ficha ya no aparece).

### TCH-PAR-21: `fecha_entrega_banco` no se actualizaba

El upsert de `tch_suscripciones` no incluia `fecha_entrega_banco`: una ficha conservaba la entrega al banco de su
primera carga (o NULL) aunque reportes posteriores la trajeran o corrigieran. Corregido en esta rama (prueba
`tests/test_tch_par21.py`). Como es el tercer respaldo de la fecha de alta, la misma recarga de la ventana OPS-11
(ficha d209) la deja al dia.

## Mientras no se recargue

Una carga incremental (`--mode incremental` o la importacion de la pantalla de administracion) se rechaza si la base
aun tiene claves antiguas, para no duplicar cuotas.

## Riesgos

- La recarga borra y reconstruye todo `tch_*`; el respaldo del paso 1 es la unica via de vuelta.
- Las migraciones solo agregan columnas; las filas actuales conservan su clave antigua hasta la recarga.
- Las consolidaciones nocturnas anteriores a la recarga dejaron `charges`/`core_payments` con claves antiguas: el paso 6
  las elimina porque ya no existen en `tch_transacciones`.

## CRM-15B: estado y monto en «Mandatos eliminados» (fix/tch-recuperador-estado-monto)

Diagnostico (lecturas agregadas de `crm`, 2026-11-13): `tch_suscripciones` se cargo completa el 2026-09-16, antes de
TCH-PAR-05/06. Por eso `monto` esta NULL en las 29.295 fichas (el ETL de entonces leia «Ingreso», una fecha) y el
estado salia de la hoja, no de la columna ESTADO: 8 fichas VIGENTE con `fecha_eliminacion` (IG sep-2026, ESTADO
«Eliminado», baja de oct-2026), 5 ELIMINADA con ESTADO «Activo», 3 VIGENTE con ESTADO «Rechazado» y 113 «Pendiente»
como VIGENTE. El codigo actual ya lee «Monto Vigente» y ESTADO; esta rama agrega:

- Una ficha con «Fecha Eliminado» no queda VIGENTE/PENDIENTE aunque ESTADO diga «Activo» (IG dic-2017: 5 fichas de
  la hoja ELIMINADOS).
- «El reporte mas nuevo gana» tambien para la ficha: cada fila guarda el mes del reporte en
  `raw_payload._reporte_periodo` y un reporte anterior cargado despues no la sobrescribe (sin migracion). Las filas
  sin esa clave (la carga actual) se actualizan normalmente.

No hace falta un comando aparte: la misma recarga completa de la ventana OPS-11 (ficha d209, pasos 1 a 7 de arriba)
deja `monto` y `estado` al dia, y el paso 6 (`run_tch_core_etl`) los lleva a `core_subscriptions`, que es lo que lee
el recuperador. Verificacion despues (solo lectura): `SELECT count(*) FROM core_subscriptions WHERE source='tch' AND
amount IS NULL` cercano a 0 y `... AND status IN ('VIGENTE','PENDIENTE') AND ended_at IS NOT NULL` = 0.
