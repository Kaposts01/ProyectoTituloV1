# Suite de contrato VirtualPOS (doc vs sandbox)

Detecta contradicciones entre la documentacion (`docs/integrations/virtualpos/`) y el proveedor.
Cada prueba registra esperado vs observado (`claim.check`); el desacuerdo NO falla la prueba.

Ejecucion (PowerShell, desde la raiz; llama al sandbox real, ejecutar solo a proposito):

```powershell
$env:APP_ENV='sandbox'; $env:CONTRACT_TESTS='1'; $env:CONTRACT_WRITES='1'; $env:VIRTUALPOS_SANDBOX_WRITES_ENABLED='true'; $env:CONTRACT_VP_SUB_FIXED='<id>'; $env:CONTRACT_VP_SUB_VARIABLE='<id>'; .venv\Scripts\pytest.exe tests_contract -m contract -q -p no:cacheprovider
```

- Alternativa si los lanzadores del venv fallan: `.venv\Scripts\python.exe -m pytest ...`.
- Solo lectura: omite `CONTRACT_WRITES` y usa `-m "contract and not contract_write"`.
- Informe: `reports/contract/virtualpos/drift-<fecha>.json` y `.md` (claim, documento, esperado,
  observado, coincide, fecha, HTTP, E-nnn). Saneado: sin llaves, firma, PAN ni RUT. Esta en `.gitignore`.
- Escritura: crea cargos `pendiente` (hoy+20 dias, `internal_code` `CT-...`) y al final cancela los que sigan
  pendientes; si la limpieza falla, la sesion termina con error.
- Guardas: aborta si `APP_ENV` no es sandbox, si el host no es exactamente el de sandbox, o sin `CONTRACT_TESTS=1`.
  NUNCA se ejecuta contra produccion. La suite normal (`pytest -q`) no las recolecta.

## Lotes

| Lote | Archivo | Pruebas | Marca | Estado |
| --- | --- | --- | --- | --- |
| 1 (VP-LEC) | `virtualpos/test_read_claims.py` | 10 (VP-C01, C08, C14, C15, C16, C19, C26, C28, C30, C31) | `contract` | Catalogado, automatica |
| 2 (VP-ESC) | `virtualpos/test_write_claims.py` | 9 | `contract` + `contract_write` | Catalogado, avisar |
| 3 (CT-xx, BILL-11) | `virtualpos/test_p0_option_a.py` | 8 recetas P0 | `contract` + `contract_write` | **Escritas, sin ejecutar; pendientes de aprobacion en bloque** (DEC-45) |

- VP-C30 y VP-C31 (DEC-46) repiten V-2 y V-3 del `VALIDATION-PLAN`: el detalle de un cargo pagado trae
  `payment.order.uuid` y ese uuid aparece en `/v3/payments` con `payment_method` PAT. El informe guarda solo
  nombres de campos, conteos y booleanos (nunca uuid, montos ni datos de cliente).
- Si el worktree no tiene `.env`, pasar la ruta del `.env` del repo principal en `CRM_DOTENV_PATH` (variable de proceso).

## Recetas P0 de la opcion A (lote 3)

Ademas de las guardas de escritura exigen `CONTRACT_CT_P0=1` (aprobacion en bloque) y `CONTRACT_CT_PHASE`
(`arm` crea y deja armado; `observe` mide cuando pasa la fecha y limpia). Sin esas variables se omiten.
Cada receta usa una suscripcion NUEVA y dedicada, creada por una persona con el formulario publico del plan y las
tarjetas oficiales de sandbox (https://virtualpos.readme.io/reference/datos-de-prueba-sandbox); su id se pasa solo
como variable de proceso y si falta la receta se omite:

| Receta | Variable(s) | Fases | Tope |
| --- | --- | --- | --- |
| CT-00 | `CONTRACT_CT_00_SUB` | arm, observe | 1 cargo |
| CT-CO-AUTO | `CONTRACT_CT_CO_AUTO_SUB` | arm | 3 cargos (usa 2) |
| CT-CO-DUP | `CONTRACT_CT_CO_DUP_SUB` | arm, observe | 1 cargo |
| CT-CO-NC3 | `CONTRACT_CT_CO_NC3_SUB` | arm | 3 cancelaciones de automaticos, 3 cargos |
| CT-RZ-MC | `CONTRACT_CT_RZ_MC_SUB`, `CONTRACT_CT_RZ_CARD_REJECT=1` | arm, observe (4 dias) | 1 cargo |
| CT-RZ-SWAP | `CONTRACT_CT_RZ_SWAP_SUB`, `CONTRACT_CT_RZ_CARD_REJECT=1`, luego `CONTRACT_CT_RZ_CARD_OK=1` | arm, observe | 1 cargo, 2 reintentos |
| CT-CANCEL | `CONTRACT_CT_CANCEL_SUB` y `CONTRACT_CT_CANCEL_CONFIRM` (mismo id) | arm | 2 cargos + 1 POST que debe rechazarse |
| CT-STALE | `CONTRACT_CT_STALE_SUB` | arm, observe | 1 cargo |

- Los cambios de tarjeta los hace una persona en el link de `changecard`; la prueba nunca recibe numeros de tarjeta.
- Los cargos que esperan su fecha quedan en `reports/contract/virtualpos/ct-p0-state.json` (solo ids) y la fase
  `observe` los cancela si siguen `pendiente`; el resto lo cancela `created_charges` al final de la sesion.
- `/retry` se llama una sola vez por intento (sin el backoff de lectura). Nunca se usa el DELETE plural.
- CT-STALE mide al proveedor con el cliente de la suite; no usa `apply_change_request` ni decide DEC-30.
