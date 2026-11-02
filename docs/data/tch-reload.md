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
   .venv\Scripts\python.exe scripts\etl_tch.py --mode full --folder "C:\Users\Usuario\Downloads\CRM_reportes\TCH" `
     --exclude-months 2023-01,2023-02,2023-03,2023-04,2023-05,2023-06,2023-07,2023-08,2023-09,2023-10,2023-11,2023-12
   ```

   Imprime por mes las cuentas aceptadas/rechazadas de la base reconstruida frente al control y los meses que no
   cuadran. Umbrales por defecto: 0,5 % por mes y 0,1 % total (`--tolerance-month`, `--tolerance-total`). Si hay meses
   en `FALLA`, no continue: revise primero.
5. **Apply** (solo si el dry-run cuadra). Exige el nombre exacto de la base:

   ```powershell
   .venv\Scripts\python.exe scripts\etl_tch.py --mode full --folder "C:\Users\Usuario\Downloads\CRM_reportes\TCH" `
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

## Mientras no se recargue

Una carga incremental (`--mode incremental` o la importacion de la pantalla de administracion) se rechaza si la base
aun tiene claves antiguas, para no duplicar cuotas.

## Riesgos

- La recarga borra y reconstruye todo `tch_*`; el respaldo del paso 1 es la unica via de vuelta.
- Las migraciones solo agregan columnas; las filas actuales conservan su clave antigua hasta la recarga.
- Las consolidaciones nocturnas anteriores a la recarga dejaron `charges`/`core_payments` con claves antiguas: el paso 6
  las elimina porque ya no existen en `tch_transacciones`.
