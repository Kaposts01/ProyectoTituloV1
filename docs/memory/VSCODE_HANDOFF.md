# Continuidad de SynkmetriX en VS Code

Fecha: 2026-10-20 (America/Santiago).

## Instruccion del usuario

Continuar este mismo proyecto desde el agente de VS Code. Trabajar en la rama local existente con commits pequenos y verificados; al finalizar la etapa acordada se preparara un unico commit de entrega para GitHub conservando el historial local. No hacer push ni fusionar master sin indicacion del usuario.

Primero leer AGENTS.md, docs/memory/PROJECT_STATE.md y docs/memory/CURRENT_SPRINT.md. Las nueve skills de stack estan en .agents/skills; cargar solo las pertinentes. Las skills de gobierno originales siguen en .opencode/skills.

## Checkout y resultado

- Repositorio: C:/Users/cristopher/Documents/Proyectos/ProyectoTituloV1.
- Rama: codex/estabilizacion-synkmetrix. Ultimo commit antes de este traspaso: 9d9587a.
- Remoto origin/master conocido: 4604258; no se ha publicado el trabajo local.
- Ultima entrega DASH-02 completada: dashboard general con KPI mensuales y cuatro graficos siguiendo referencias visuales. El usuario confirmo que imagenes, cifras y categorias eran solo referencias de diseno.
- Nuevos archivos: app/services/dashboard_performance.py; frontend/src/features/dashboard/GeneralPerformance.tsx, GeneralPerformance.css y performanceModel.ts; tests/test_dashboard_performance.py; frontend/tests/performance-model.test.mjs.
- Campo adicional performance en GET /api/v1/staging/dashboard/general. No cambia permisos ni esquema.
- Interfaz: selector de mes, meta opcional de analisis por ano, rangos 12 meses/ano/todo, tablas por grafico, resumen operativo anterior desplegable.
- No confundir suscripciones reconstruidas por fuente con socios unicos. Excluir monedas no verificadas, fechas futuras y controles TCH vacios; control TCH reemplaza detalle solo en su mes. No sumar copias TCH de la proyeccion centralizada.
- Meta de analisis solo en memoria: no hay meta institucional confirmada ni persistencia. Proyeccion aritmetica solo con meses cerrados observados desde enero. No se agregaron Etas ni donaciones individuales sin fuente.
- Definiciones, evidencia y limites: docs/quality/dashboard-kpis-2026-10-20.md.

## Commits previos relevantes

- 9d9587a: interfaz de KPI y graficos, pruebas frontend, CI y documentacion.
- 6dde547: calculos mensuales observados y pruebas backend.
- 22754cd / eca7182: integridad, atributos compartidos por cliente, migracion 0032 y vinculos VP conservadores.
- fe9af42 / 8bb7a6a: resultados ETL honestos, rutas Core estaticas antes de dinamicas e imports CLI reparados.
- b46e1b4 / 0e846f3: documentacion y nueve skills evaluadas.
- 544ea47: metadata webhooks, pruebas y check Alembic en CI.

## Entorno y validacion real

- Windows PowerShell, .venv Python 3.14.7. El proyecto declara 3.14.5; no certificar igualdad exacta con CI.
- PostgreSQL 18 nativo aislado del proyecto, 127.0.0.1:5433, base crm, Alembic 20261020_0032. Docker PG17 bloqueado por virtualizacion; no iniciar ni reemplazar otra base para ocultarlo.
- API: http://127.0.0.1:8000. Frontend: http://127.0.0.1:5173/central/resumen. Reutilizar procesos si siguen activos y comprobar salud antes de reiniciar.
- Ultima validacion: 304 pruebas Python aprobadas en base PostgreSQL de pruebas aislada; 4 pruebas frontend (npm test); Ruff global, lint y build pasan.
- Persisten 11 advertencias frontend, aviso de bundle mayor a 500 kB y deprecacion Starlette/httpx. No se corrigieron escondiendo checks.
- Dashboard revisado en sesion autenticada: selector, meta temporal, rango y tabla. Conciliacion TCH septiembre coincide. Sin prueba en dispositivo movil real.
- No ejecutar pytest contra crm operativo. Runner local ignorado .local/validate_update.py prepara variables sinteticas y usa synkmetrix_validation_568eac70a1. Inspeccionarlo antes de reutilizarlo; usa .env internamente sin imprimir secretos.
- Logs en logs/. Captura local del dashboard en .local/dashboard-general-kpis.png; no versionar datos locales ni respaldos.

## Datos e integraciones

- VP1 se cargo desde Sandbox; no equivale a produccion. VP2 y Payku sin configuracion util para esta carga.
- Toku tiene clientes, suscripciones y facturas, pero /organization/payments devuelve 404. La carga acotada se documento como cobertura incompleta; no declarar que no existen pagos ni inventar un endpoint alternativo.
- TCH viene de reporte Excel de septiembre 2026. No reimportar ni hacer ETL full como prueba.
- Se aplicaron migraciones hasta 0032 con respaldo previo. No se hizo backfill ni reasignacion historica de relaciones; no prometer reparacion retroactiva.

## Continuacion sugerida, pendiente de prioridad del usuario

La tarea del dashboard esta terminada. Primero informar que se leyo el contexto y pedir la siguiente tarea concreta; no ejecutar pendientes por el mero hecho de que figuren aqui. Posibles siguientes trabajos: contrato de pagos Toku, cache segura ante cambio de sesion/cuenta, advertencias React y modularizacion progresiva.

## Limites permanentes

- Secretos solo en .env; nunca imprimir claves, cookies o credenciales. No incluir PII ni datos de tarjeta en logs/documentos.
- Proveedores en solo lectura; escrituras requieren tareas WR implementadas y sus flags. No crear/reintentar cobros ni enlaces por tener una clave.
- Preservar Fuentes -> Connectors -> Raw/STG -> ETL -> PostgreSQL Core -> API -> CRM.
- RUT/email/telefono compartidos no autorizan merges; respetar ADR-001. Migraciones aplicadas inmutables.
- postman/ es un repositorio Git anidado; no borrar su .git ni usar git add . indiscriminadamente.
