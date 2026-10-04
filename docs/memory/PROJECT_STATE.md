# Estado del Proyecto

Fecha de actualizacion: 2026-10-02.

## Estado actual

El repositorio contiene un CRM operativo con FastAPI, PostgreSQL, React/Vite, autenticacion, permisos, staging y trazabilidad por canal. VirtualPOS, Toku y Payku se sincronizan desde APIs; TCH se carga desde reportes Excel. La vision objetivo es un CRM para fundaciones que centralice socios, donantes y suscripciones de multiples fuentes.

## Completado

- Staging saneado e idempotente para canales API.
- Tablas y vistas operativas por canal, dashboards y reportes existentes.
- Autenticacion, permisos y registro de sincronizaciones y escrituras autorizadas.
- Vault documental de Obsidian y documentacion conceptual inicial.
- La estructura versionada separa scripts operativos, mantenimiento y diagnostico; la documentacion historica y las colecciones Postman tienen ubicaciones explicitas; los insumos locales se excluyen bajo `data/local/` y `.local/`.
- Skill local `project-memory` disponible para gestionar memoria persistente y ADRs compactos; su descubrimiento fue confirmado en una sesion reiniciada de OpenCode.
- Skill local `data-modeling` disponible para disenar y revisar el modelo centralizado; su descubrimiento, ruta y frontmatter fueron confirmados en una nueva sesion de OpenCode.
- Skill local `provider-integration` disponible para estandarizar connectors, Raw/STG, contratos y seguridad de proveedores; su descubrimiento fue confirmado en OpenCode.
- Definiciones locales de los subagentes `obsidian-vault` y `adr-governance` disponibles para mantener el vault y gobernar ADRs sin redefinir las fuentes de verdad del proyecto.
- La configuracion y skills de OpenCode son parte versionable del proyecto; los ajustes especificos de Claude permanecen locales y no definen reglas del proyecto.
- OpenCode mantiene la integracion compartida de Context7; Claude puede usar una configuracion local complementaria bajo las reglas de `AGENTS.md`.
- El vault de Obsidian se abre desde la raiz del repositorio para incluir `docs/` y `knowledge/`; `.obsidian/` conserva solo preferencias locales.
- El frontend usa el proxy de Vite hacia la API local en `127.0.0.1:8000`; el healthcheck de PostgreSQL usa las variables de Compose.
- Python 3.14.5 y sus dependencias quedan bloqueados en `.python-version` y `requirements.lock`; existe CI para backend y frontend.
- El resumen operativo de VirtualPOS prioriza recursos, indicadores, estados y tendencias. Su estado de sincronizacion proviene del ultimo `SyncRun` de sus dos cuentas y no presenta una consolidacion pendiente como hecho.
- Los dashboards de frontend usan caché en memoria con TTL de cinco minutos y deduplicación de solicitudes; la navegación reutiliza resultados válidos y las sincronizaciones invalidan la caché. TCH normaliza sus colecciones de resumen antes del render para tolerar series ausentes; el diferimiento de gráficos mensuales queda pendiente de una extracción segura de vistas.
- La SPA usa rutas navegables para la operación consolidada, canales, administración, perfil y fichas de VirtualPOS, Toku y Payku. Las fichas de proveedor usan identificadores externos; las fichas que hoy dependen de RUT conservan navegación interna hasta disponer de identificadores no personales. La URL se sincroniza con la vista, historial y permisos visibles sin cambiar contratos API ni controles de FastAPI.
- Los listados consolidado y de proveedores conservan su estado operativo seguro en query parameters: paginación, campo seleccionado, estado, orden y cuenta VirtualPOS. Los términos de búsqueda no se incluyen para evitar exponer atributos personales en URL.
- Las fichas de suscripción TCH usan `numero_ficha` de DUES en la ruta. Es un identificador único de la proyección TCH y no expone atributos personales.

## En progreso

- Tareas operativas registradas en [tasks.md](../tasks.md), incluidas Payku, Toku, administracion de usuarios y un flujo de VirtualPOS.
- Los dashboards operativos de VirtualPOS, Toku, Payku y TCH tienen paridad de KPIs, distribuciones, altas/bajas, series de suscripciones activas, churn y alertas usando solamente los campos verificables de cada fuente. Toku usa transacciones reales para su comparación con suscripciones; Payku mantiene su límite de cobertura histórica; TCH se basa en su proyección ETL.
- Payku reconoce el identificador histórico `transaction` cuando su payload no trae `id`. La reconstrucción local `scripts/maintenance/backfill_payku_transactions.py` materializa transacciones ya preservadas en `source_records` hacia `p_transactions`; luego el ETL normal las proyecta a `payments`, restaurando los años y la actividad mensual verificables del dashboard.

## Pendiente

- Definir contrato de liquidaciones, taxonomia comun y gobierno de datos personales.
- Planificar el Core tecnico desde el modelo conceptual aprobado antes de iniciar su implementacion.
- Evaluar analitica predictiva en una fase posterior.

## Bloqueos

- Payku no permite recuperar de forma confiable cierto historial de transacciones.
- VirtualPOS puede tener cargos historicos incompletos para algunas suscripciones.

## Decisiones aceptadas

- **Status: Accepted** PostgreSQL es la fuente central de verdad.
- **Status: Accepted** Cada proveedor tiene staging independiente y trazable.
- **Status: Accepted** Ningun proveedor escribe directamente en tablas Core.
- **Status: Accepted** Credenciales y API keys no se almacenan en Git.
- **Status: Accepted** Las integraciones deben poder reprocesarse.
- **Status: Accepted** La identidad centralizada usa CLIENTE con identificador interno, identidades externas trazables, matching conservador y merge reversible ([ADR-001](../decisions/ADR-001-identidad-centralizada-socios.md)).

## Decisiones TBD

- **Status: TBD** Esquema fisico, umbrales de matching y gobierno de atributos personales para la identidad centralizada.
- **Status: TBD** Contrato de liquidaciones y reglas financieras transversales.
- **Status: TBD** Gobierno de atributos personales, retencion y rectificacion.
- **Status: TBD** Taxonomia comun de estados, montos, monedas y periodicidad.

## Deuda tecnica conocida

- La base actual no supera CI: `pytest` presenta 7 fallos y `ruff check app tests alembic scripts` reporta 62 hallazgos; requieren una tarea dedicada sin mezclar cambios funcionales en curso.
- Documentos historicos de arquitectura y ETL son antecedentes y pueden no reflejar la arquitectura vigente.
- Auditoria 2026-10-01: Payku no certifica cobertura historica de transacciones y TCH requiere ampliar su cobertura ETL mas alla de la suite focalizada inicial. Estos limites deben considerarse al usar sus metricas como evidencia completa.
- El frontend concentra estado, carga de datos, dashboards y exploradores en `frontend/src/App.tsx`. La resolución de rutas se extrajo a `frontend/src/routes.ts` y las alertas operativas a `frontend/src/features/dashboard/OperationalAlerts.tsx`; la modularización restante debe preservar permisos y contratos API por canal.
- Auditoria 2026-10-01: VirtualPOS conserva los cargos embebidos en suscripciones porque los pagos no incluyen una referencia que permita unirlos 1:1. La conciliacion actual solo puede ser agregada por plataforma, estado y monto. Payku sincroniza transacciones embebidas, sin certificar cobertura historica. El ETL TCH sanea Raw y su modo `full` es atomico; su suite focalizada inicial esta disponible.
- VirtualPOS materializa solo los `source_records` que cambiaron durante la sincronizacion. Antes releia y rematerializaba todo el historial de la plataforma, lo que degradaba las sincronizaciones y bloqueaba sus pruebas contra bases con datos reales.
- DB-02 y DB-03 confirmadas: la instancia efectiva es PostgreSQL 17 en `localhost:5433/crm`, persiste en `crm_projectotitulo_postgres_data` y esta en Alembic `20261001_0023` (`head`). La migracion reconcilio imports, metadata e indices; `alembic check` no detecta operaciones pendientes y las estadisticas TCH se actualizaron.

## Convencion terminologica

En SynkmetriX se utilizara el termino modelo centralizado en lugar de modelo canonico.
