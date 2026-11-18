# Actualizacion local y comparacion — 2026-11-18

> Comparacion inicial. La reparacion posterior, el entorno operativo y los resultados vigentes estan en [reparacion local](local-repair-2026-11-18.md).

## Base y alcance

Rama local `codex/actualizacion-20261118` creada desde `origin/master` en `54814f4` (2026-11-16). Las ramas `sprint-5/estabilizacion-dashboard` (`1005a26`) y `codex/estabilizacion-synkmetrix` (`5abb924`) se conservan. No se fusiona a master, no se publica y no se migra la base operativa.

La comparacion no es un cherry-pick del commit antiguo: la version actual incorpora 604 commits exclusivos desde el ancestro comun y ya adapto parte de ese trabajo.

## Resultado por area

| Avance de 1005a26 | Estado en la version reciente | Accion |
| --- | --- | --- |
| Nueve skills Codex, metadatos, referencias y evaluaciones offline | Ausentes | Recuperados los paquetes y pruebas estructurales; AGENTS registra su alcance sin reemplazar las reglas nuevas. La evaluacion de comportamiento fechada en octubre sigue siendo historica. |
| CLI de sincronizacion y rutas Core estaticas | Incorporados; pruebas `test_rev01_sync_reliability.py` | Conservar implementacion actual. |
| Fallos parciales, logs saneados y cierre SSE | Adaptados en REV-01 y trabajos posteriores | Conservar estado `partial` vigente; no reinstalar el contrato antiguo de errores terminales. |
| Fixture transaccional del detector de matching | Incorporada con referencia explicita a 1005a26 | Conservar. |
| RUT ambiguo VirtualPOS e ID externo prioritario | Incorporados en `core_vp_etl.py` | Conservar. |
| Dashboard mensual, acumulado, meta y proyeccion | Reemplazado por componentes y contratos de graficos actuales | No copiar App.tsx ni estilos TECHO antiguos sobre el sistema actual. No se afirma equivalencia financiera completa sin una auditoria de KPI. |
| Unicidad de atributos por cliente y fuente | Pendiente: el modelo actual conserva UNIQUE(source, attribute_type, attribute_value) | No trasladar automaticamente la revision 0037 antigua: ese numero ya esta ocupado y la cadena actual llega a 0081. Evaluar por separado nueva migracion y pruebas con el modelo vigente. La implementacion anterior permanece en la rama sprint-5. |
| Informes y memorias de octubre | Historicos | No sobrescribir el plan ni la memoria vigente con estados antiguos. |

## Validacion

Dependencias instaladas desde requirements.lock en `.local/validation-20261118/.venv`; pip check pasa y la `.venv` de trabajo se conserva. Frontend usa npm ci sin modificar los locks. Se uso tambien la skill project-memory para registrar el estado local y los limites de validacion.

`npm audit` detecta siete paquetes con severidad alta: `@vitest/coverage-v8`, `fdir`, `picomatch`, `source-map-js`, `tinyglobby`, `vite` y `vitest`. Es el resultado del arbol instalado, no siete fallos independientes ni una prueba de explotabilidad. No se aplico `npm audit fix` ni se cambiaron versiones.

## Limites operativos

- El cambio de checkout no actualiza esquemas ni configura el entorno de operacion de la version reciente.
- La base local antigua tenia una revision 0032 distinta de la publicada; no ejecutar upgrade sobre ella sin reconciliar y respaldar.
- La migracion publicada 0035 ahora usa `sa.Column`; el bloqueo documentado en octubre no sigue vigente en esta base de codigo.
- Las skills recuperadas no autorizan escrituras a proveedores ni sustituyen las decisiones actuales de AGENTS y docs/tasks.md.

### Resultados verificados

- Ruff `check app tests alembic scripts`: pasa.
- Pytest sin conftest de aplicacion: 71 pruebas pasan (37 de skills y 34 de guardas de base), con las dependencias nuevas y sin acceder a PostgreSQL.
- Lint frontend: sin errores; conserva advertencias React.
- Build frontend: pasa. El mayor chunk es vendor-charts, 408,43 kB.
- Suite Python completa: no pudo iniciarse por timeout de conexion PostgreSQL local en 5433 durante la preparacion de la base exclusiva de pruebas. No se certifican migraciones aplicadas ni backend funcional; no se migro la base operativa.
- Suite frontend completa: interrumpida al dejar de avanzar tras un fallo. Reproduccion focalizada: falla por snapshot HTML distinto en `staging.characterization.test.tsx`, caso «pide dashboard/{canal} una vez y muestra el resumen operativo con los accesos a recursos». No se aprobaron snapshots nuevos ni se modifico codigo frontend. No se certifica la suite completa.
- No se arrancaron servidores ni se hicieron llamadas o escrituras a proveedores.
