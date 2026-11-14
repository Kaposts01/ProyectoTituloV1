# Guion de la demo y video de respaldo (DOC-15)

- **Tarea:** DOC-15, sección 3.11 (S7) de [`docs/tasks.md`](../tasks.md).
- **Decisión de origen:** d161 (demo en vivo sobre la producción local).
- **Dependencia:** SEC-02, modo demo que enmascara datos personales (ficha d199).
- **Estado:** guion redactado; sin ensayar.

> **Advertencia.** Este guion no se puede ensayar en vivo hasta que SEC-02 exista y esté verificado (ficha d199). La producción local (`crm`) tiene datos personales reales de socios: sin el modo demo, cualquier listado, ficha o CSV los mostraría al comité. Mientras SEC-02 no esté, solo se puede revisar el texto del guion y cronometrar el recorrido en el sandbox sobre filas `DEMO-`, sin grabar (regla 14 del [runbook](../operations/sandbox-testing-and-decisions.md), QA-04). El video de respaldo tampoco se puede grabar hasta entonces.

## 1. Objetivo y mensaje

Mostrar en 10 a 12 minutos que el CRM reúne en un solo lugar los socios y cobros de los cuatro canales (VirtualPOS, Toku, Payku y TCH), que detecta los cobros que fallan y que ofrece un flujo controlado para actuar sobre ellos.

Mensaje en una frase: «Antes había que revisar cuatro plataformas y planillas; ahora el equipo ve el estado de cada socio y actúa desde una sola pantalla, con aprobación y trazabilidad».

## 2. Recorrido (10 a 12 minutos)

Los tiempos son acumulados. Si se va atrasado, se acorta el bloque 6 (exportar) y luego el 5 (bajas).

| Bloque | Tiempo | Pantalla | Qué mostrar | Qué decir (idea) |
|---|---|---|---|---|
| 0. Apertura | 0:00–1:00 | Pantalla de inicio con sesión ya iniciada | Banda o indicador de modo demo encendido | El problema: cuatro canales, datos dispersos. Aviso: «los datos personales están enmascarados». |
| 1. Resumen general | 1:00–3:00 | `/central/resumen` | Tarjetas KPI (suscripciones activas, MRR, churn, cargos rechazados), un gráfico de tendencia, indicador de salud de sincronización en la barra lateral | Cada gráfico responde una pregunta. La salud de canal dice si los datos están al día. |
| 2. Consultar un socio | 3:00–4:30 | Buscador → Clientes consolidados → ficha | Búsqueda por identificador enmascarado; ficha con sus suscripciones y cobros de varios canales | Identidad unificada entre canales. Los datos personales aparecen enmascarados. |
| 3. Cobros rechazados | 4:30–6:00 | Cobros y resumen por canal | Filtro de rechazados, motivo del rechazo | De dónde sale el motivo y cómo se normaliza por canal. |
| 4. Recuperador | 6:00–7:30 | `/virtualpos/recuperador-socios` | Lista de socios recuperables y la acción sugerida | Prioriza a quién contactar; no hace cobros por su cuenta. |
| 5. Cambio de cobro | 7:30–9:30 | `/general/cambios-de-cobro` | Pestaña Pendientes, detalle de una solicitud con advertencias, diálogo «Nueva solicitud» y diálogo «Aprobar» **sin confirmar** | Separación entre quien solicita y quien aprueba; historial y renovaciones. No se ejecuta ningún cambio real. |
| 6. Bajas y exportar | 9:30–10:30 | `/general/bajas`, Suscripciones consolidadas → Exportar | Estado de una solicitud de baja; exportación de un listado | El CSV también sale enmascarado y queda en la auditoría de exportaciones. |
| 7. Operación | 10:30–11:15 | `/admin/sincronizaciones` | Panel del scheduler y últimas corridas | El sistema corre local, con sincronización programada y respaldo (d155, d156). |
| 8. Cierre | 11:15–12:00 | Volver al resumen | Una sola vista | Resultados de MET-01 a MET-03 (cobertura, métricas de operación, sesiones con usuarios) y trabajo futuro (terceros cortados por d154). |

Reglas durante la demo:

- No se confirma ninguna escritura (solicitudes, aprobaciones, bajas, sincronizaciones manuales). Los diálogos se abren y se cierran.
- No se usa la búsqueda libre con nombres reales; se usan identificadores preparados en la checklist.
- Si aparece un dato en claro, se pasa de inmediato al video (plan B) y se registra el defecto como P0.

## 3. Preguntas probables del comité

| Pregunta | Respuesta corta | Dónde apoyarse |
|---|---|---|
| ¿Por qué no se usó el CRM de un tercero? | Los cuatro canales tienen API distintas y reglas propias de cobro; ningún producto los integraba sin desarrollo. | `docs/architecture/`, ADR-001 |
| ¿Cómo se asegura que las cifras son correctas? | KPI y gráficos comparados con los portales de los proveedores (USR-03) y paridad por canal con `parity_check.py` (MET-01). | `docs/quality/revisiones-s7.md` |
| ¿Qué pasa si un proveedor falla o cambia su API? | Sincronización con registro de corridas (`sync_runs`), indicador de salud y suite de contrato para VirtualPOS. | MET-02, CT-01 |
| ¿Cómo se protegen los datos personales? | Roles, auditoría de exportaciones y modo demo (SEC-02). La operación es local (d155). | SEC-02 |
| ¿Puede el CRM cobrar o cambiar un cobro por error? | Los cambios requieren solicitud y aprobación de otra persona; hay guardas y script de reversión planificado. | Sprint 4, BILL-12 |
| ¿Qué quedó sin hacer y por qué? | Tareas que dependen de terceros (Payku, Toku, tarjetas de VirtualPOS) se cortaron al cierre de S7 y quedan como trabajo futuro (d154). | `docs/tasks.md` §3.11 |
| ¿Lo usaron personas reales? | 2 a 3 sesiones con jefatura y ejecutivos, con tareas guiadas y SUS (MET-03). | `docs/quality/validacion-usuarios.md` |
| ¿Cómo se despliega y respalda? | PC local como servidor, copia en disco externo y en nube cifrada (d155, d156). | Capítulo de operación de la memoria |
| ¿Cuánto cuesta mantenerlo? | Sin costo de hosting por ahora; el hosting en la nube queda como trabajo futuro. | DOC-14 |

## 4. Plan B: video de respaldo

- **Cuándo se usa:** falla de red o de un proveedor, el servidor local no responde, la sesión expira, o aparece un dato personal en claro.
- **Qué contiene:** el mismo recorrido de la sección 2, de 10 a 12 minutos, con narración o subtítulos.
- **Cómo se graba:** sobre la producción local con SEC-02 encendido, después de completar la checklist de la sección 5. Resolución 1920 × 1080, zoom del navegador al 100 %, sin notificaciones del sistema.
- **Revisión antes de usarlo:** se mira completo, cuadro a cuadro en las pantallas de listados, fichas y CSV, para confirmar que no aparece ningún RUT, nombre, correo o teléfono en claro. Si aparece uno, el video se descarta y se graba de nuevo.
- **Dónde se guarda:** fuera del repositorio, en el equipo de la presentación y en la copia en la nube cifrada (d156). Se lleva además en un pendrive.
- **Bloqueado hasta:** que SEC-02 exista (d199).

## 5. Checklist previa (el día de la demo)

- [ ] SEC-02 encendido y verificado: se recorrieron las pantallas de los bloques 1 a 7 y el CSV del bloque 6, sin ningún dato personal en claro.
- [ ] Datos enmascarados también en la barra de búsqueda, los tooltips y los diálogos.
- [ ] Indicador visible de modo demo en pantalla.
- [ ] Backend y frontend de producción local arriba; sincronización programada en pausa durante la demo para que no cambien las cifras a mitad del recorrido.
- [ ] Sesión iniciada con un usuario de rol aprobador; expiración de sesión mayor que la duración de la demo.
- [ ] Identificadores preparados para los bloques 2, 5 y 6 (enmascarados), anotados en una tarjeta.
- [ ] Red: conexión probada en la sala; si la demo no necesita a los proveedores en vivo, se trabaja sin depender de la red.
- [ ] Navegador en ventana limpia, zoom 100 %, tema decidido (claro u oscuro), notificaciones del sistema desactivadas.
- [ ] Video de respaldo revisado, copiado en el equipo y en el pendrive, y probado en el proyector.
- [ ] Carpeta de descargas vacía; el CSV del bloque 6 se borra al terminar.

## 6. Ensayos

- S7: guion cerrado; cronometraje en sandbox sobre filas `DEMO-`, sin grabar (permitido antes de SEC-02).
- S7, después de SEC-02: primer ensayo en vivo sobre la producción local y grabación del video.
- S8: al menos dos ensayos completos con la checklist y uno con el plan B (pasar al video a mitad del recorrido).

Definición de hecho (sección 3.11): demo ensayada con SEC-02 y video grabado.
