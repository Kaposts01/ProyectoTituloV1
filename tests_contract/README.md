# Suite de contrato VirtualPOS (doc vs sandbox)

Detecta contradicciones entre la documentacion (`docs/integrations/virtualpos/`) y el proveedor.
Cada prueba registra esperado vs observado (`claim.check`); el desacuerdo NO falla la prueba.

Ejecucion (PowerShell, desde la raiz; llama al sandbox real, ejecutar solo a proposito):

```powershell
$env:APP_ENV='sandbox'; $env:CONTRACT_TESTS='1'; $env:CONTRACT_WRITES='1'; $env:VIRTUALPOS_SANDBOX_WRITES_ENABLED='true'; $env:CONTRACT_VP_SUB_FIXED='<id>'; $env:CONTRACT_VP_SUB_VARIABLE='<id>'; .venv\Scripts\pytest.exe tests_contract -m contract -q -p no:cacheprovider
```

- Solo lectura: omite `CONTRACT_WRITES` y usa `-m "contract and not contract_write"`.
- Informe: `reports/contract/virtualpos/drift-<fecha>.json` y `.md` (claim, documento, esperado,
  observado, coincide, fecha, HTTP, E-nnn). Saneado: sin llaves, firma, PAN ni RUT. Esta en `.gitignore`.
- Escritura: crea cargos `pendiente` (hoy+20 dias, `internal_code` `CT-...`) y al final cancela los que sigan
  pendientes; si la limpieza falla, la sesion termina con error.
- Guardas: aborta si `APP_ENV` no es sandbox, si el host no es exactamente el de sandbox, o sin `CONTRACT_TESTS=1`.
  NUNCA se ejecuta contra produccion. La suite normal (`pytest -q`) no las recolecta.
