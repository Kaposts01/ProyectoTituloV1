# Auditoría UX/IA: CRM unificado (solo lectura, 2026-10-29)

Fuentes leídas: CLAUDE.md, DESIGN.md, handoff.md §5/§8/§10-12, docs/tasks.md (§3.6 VIZ, DEC-34..41), ADR-001, docs/designs/reconciliacion-identidad-socios.md, frontend/src (routes.ts, navigation.ts, Sidebar.tsx, AppCore.tsx, components/, features/dashboard, features/shared), app/api/v1/routes/staging.py (`_general_*`), identity.py, app/models/core.py, scripts/visual, y las 3 capturas.

## 1. Inventario actual

### 1.1 Rutas (frontend/src/routes.ts, router propio sin react-router; `AppCore.tsx` 3.666 líneas decide qué pintar)
| Ruta | Pantalla | Permiso |
|---|---|---|
| /central/resumen | Dashboard general (8 componentes viejos de MonthlyStatusChart.tsx + KPIs + alertas) | dashboard.view |
| /central/clientes | "Clientes por RUT" (rut, nombre, origins, active_origins) | dashboard.view |
| /central/suscripciones | Suscripciones consolidadas: ID, cliente, RUT, plataforma, estado, estado secundario, último cobro, inicio, término, monto (ya unificada, 4 canales) | dashboard.view |
| /central/reporte-automatico | AutomaticReport.tsx | dashboard.view |
| /{virtualpos,toku,payku}/resumen | ChannelDashboardView (KpiStrip + ChannelChart + alertas) | dashboard.view |
| /tch/resumen, /tch/clientes, /tch/suscripciones(/:ficha), /tch/transacciones | Vistas TCH con endpoints y tipos propios (`/api/v1/tch/*`) | tch.* |
| /virtualpos/{clientes,planes,suscripciones,cargos,transacciones} | Tablas genéricas de recursos staging | virtualpos.*.view |
| /toku/{clientes,suscripciones,metodos-pago,deudas,transacciones} | idem + TokuPaymentMethodProfile | toku.*.view |
| /payku/{clientes,planes,suscripciones,transacciones} | idem | payku.*.view |
| /virtualpos/recuperador-socios | Recuperador (solo VP; Sprint 5 prevé /general/recuperador con 4 pestañas) | virtualpos.recovery.view |
| /general/cambios-de-cobro (+ legacy /virtualpos/cambios-de-cobro) | Bandeja Opción A: Pendientes/Historial/Renovaciones, política | virtualpos.billing_changes.view |
| /admin/usuarios, /admin/sincronizaciones | Usuarios/roles/aprobaciones; scheduler y sync | users.manage, sync.* |
| /mi-perfil(/editar) | Perfil | sesión |

### 1.2 Menú lateral (Sidebar.tsx + navigation.ts)
Plano: Dashboard; anidados: Clientes, Suscripciones, Reporte automático, Cambios de cobro. Luego 3 grupos expandibles (VirtualPOS 5 ítems + Recuperador; Toku 5; Payku 4), TCH (3), Administración (2). Punto de salud por canal. Total: unas 25 entradas, 4 de ellas llamadas "Clientes" y 4 "Suscripciones/Subscripciones" (ortografía inconsistente) más "Cargos/Transacciones/Deudas" según canal.

### 1.3 Duplicación
- Clientes: 5 vistas (general por RUT + 4 por canal) con columnas distintas; nombres de campo distintos por canal (VP `social_id`, TCH `rut`, Toku customer).
- Suscripciones: 5 vistas; la general ya une CSub + TchSuscripcion con `platform`, así que la unificación de lista **ya existe en backend** (`_general_subscriptions`) y solo falta promoverla.
- Cobros: VP "Cargos", Toku "Deudas" (invoice), Payku/Toku/VP "Transacciones", TCH "Transacciones": 4 nombres para el mismo concepto cobro/intento. Existe `core_charges`/`core_payments` en Core pero no hay vista unificada.
- Dashboards: 5 (general + 4), con dos pipelines de gráficos (ChannelChart nuevo y MonthlyStatusChart viejo con hex fijos, sin modo oscuro, 2 componentes muertos).
- Recuperador: solo VP hoy; Cambios de cobro ya está en "general/" pero cuelga del grupo VP en permisos (`virtualpos.billing_changes.view`).
- Backend: `/dashboard/general/clients` agrupa por `_rut_key` sobre tablas **legacy** (`clients` + `tch_clientes`), no sobre Core. Es la causa del titular "39.730 clientes por RUT" que el diseño de reconciliación declara como supuesto no verificado.

## 2. Arquitectura de información propuesta

### 2.1 Menú lateral (un nivel, sin submenús por canal)
```
SynkmetriX
  RESUMEN
    Resumen            (/resumen)              tabs: Mes · Evolución · Cartera (Plan 2030 después)
  CARTERA
    Socios             (/socios, /socios/:id)
    Suscripciones      (/suscripciones, /suscripciones/:canal/:id)
    Cobros             (/cobros)               cargos + transacciones + deudas, canal como columna
  OPERACIÓN
    Recuperador        (/recuperador)          pestañas por canal solo como filtro
    Cambios de cobro   (/cambios-de-cobro)
    Identidad          (/identidad)            cola de candidatos (hoy sin pantalla; ver DEC-08)
  SISTEMA
    Sincronización     (/admin/sincronizaciones)   incluye la salud por canal (hoy puntos en sidebar)
    Administración     (/admin/usuarios)
    Reportes           (/reportes)             reporte automático
  [pie: tema, perfil]
```
Salud de canal: se mueve a una franja "Canales" en Resumen y a la página Sincronización; el sidebar conserva un único indicador global (punto verde/ámbar).
Los recursos específicos (planes, métodos de pago, deudas) dejan de ser ítems de menú y pasan a pestañas del panel de detalle o a filtros de Cobros. Las rutas viejas se mantienen con `legacyRedirectPath` (ya existe el mecanismo en routes.ts) hacia `/socios?canal=toku`, etc.

### 2.2 Páginas
- **Resumen**: ver §3. Selector de mes, pestañas, filtro de rango (Últimos 12 meses / Año / Todo), "Ver datos" (tabla alternativa), filtro global de canal (chips: Todos · VP · Toku · Payku · TCH).
- **Socios**: tabla única. Columnas comunes: Socio (nombre), RUT (mono), Canales (tags), Estado agregado (activo si tiene alguna suscripción activa), Suscripciones activas (n), Monto mensual vigente (suma `monto_vigente`), Último cobro pagado, Alta (primera suscripción), Alerta de recuperable. Filtros: canal (multi), estado, recuperable, con identidad por revisar, rango de alta. Búsqueda: RUT, nombre, correo, teléfono, ID externo (cualquier canal).
- **Ficha de socio** (`/socios/:id`, drawer en móvil, DEC-14): cabecera (nombre, RUT, estado, banner de evidencia de identidad), pestañas Resumen · Suscripciones · Cobros · Identidad · Historial. Panel por canal dentro de la pestaña (acordeón/tarjetas de canal, sin anidar cards: separador y encabezado, no card dentro de card):
  - VirtualPOS: cuenta (vp1/vp2), plan, `monto_vigente`, día de cobro (`charge_day`), racha de rechazos, tarjeta (vencida/bloqueada, sin PAN), enlace a Cambios de cobro.
  - Toku: customer id, método de pago (chargeable), deudas/invoices, flow.
  - Payku: plan, MRR desde la última transacción success, aviso "cobertura no certificada".
  - TCH: n.º de ficha, estado Excel, equivalente en pesos, fecha de reporte (aviso si >7 días).
- **Suscripciones**: la tabla general actual (ya con `platform`), más columnas Socio (link a ficha), Monto vigente, Día de cobro, Racha de rechazos, Canal-específico en el panel lateral. Filtros: canal, estado, estado secundario (cobrable/incobrable/nunca cobrado/inactiva), rango de monto.
- **Cobros**: unifica Cargos (VP/TCH), Deudas e invoices (Toku), Transacciones (Payku/Toku/VP). Columnas: Fecha, Canal, Socio, Suscripción, Monto, Estado normalizado (pagado/rechazado/pendiente/anulado según `charge_stats.py`, una sola definición), Código de rechazo (mono). Fuente recomendada: `core_charges` + `core_payments`.
- **Recuperador**: `/recuperador` con filtro de canal (no pestañas de menú); REC-04..06 lo requieren de todos modos.
- **Cambios de cobro, Sincronización, Administración**: sin cambio funcional; solo reubicar y renombrar permisos de ruta (`/general/...`).
- **Búsqueda global** (cabecera, atajo `/`): una caja que resuelve a socios por RUT/nombre/correo/ID externo y suscripciones por ID; resultados agrupados "Socios · Suscripciones". Reutiliza `filter_field=all` del backend.

### 2.3 Unión de socios entre canales respetando ADR-001
Hoy `_general_clients` colapsa por `_rut_key`, lo que contradice ADR-001 (RUT no es clave ni prueba de merge) y la nota de reconciliación (538 grupos con colisión entre plataformas, 1,4 % del padrón; 1.097 clientes). Propuesta:
1. **Unidad de lista = `core_clients.id` (UUID)**, no el grupo de RUT. Cada fila lleva sus `external_identities` (source, resource_type, external_id). Un socio con identidad en VP y Toku solo se muestra como uno si hay vínculo `external_identities.client_id` común (nivel A, determinístico o decisión humana aprobada).
2. **Coincidencias por RUT sin vínculo** (nivel B/C/D) NO se fusionan: se muestran como insignia "Posible mismo socio (n)" en la fila y en la ficha, con enlace a la cola de identidad. El número de socios se publica como en C6: "personas con RUT" con rango y "grupos por RUT" con nota de población, separando estimado de verificado.
3. **Ficha**: la pestaña Identidad lista identidades por canal, valores observados de RUT/correo/teléfono por fuente (nunca sobrescritos), y candidatos pendientes. Acciones de confirmar/rechazar solo con `core.identity.review` y auditoría (sin ese camino de escritura el review hoy no repunta nada: dependencia de CORE/DEC-08).
4. **Bloqueo**: migrar la lectura del frontend de legacy a Core ("Migrar lecturas del frontend hacia el Core", C6a fuera de ciclo) es prerrequisito del número "personas". Mientras tanto, la vista Socios puede salir en modo transitorio: filas por grupo de RUT, rotuladas "Socios (agrupados por RUT, no verificado)" con la nota de población, exactamente la honestidad que pide el documento de reconciliación.
5. Casos de la tabla ADR (dos IDs de Toku para un cliente; misma persona en VP+Payku+Toku) se resuelven mostrando varias identidades dentro de una ficha, nunca varias filas fusionadas silenciosamente.

## 3. Capturas de inspiración -> KPIs

Estructura de la captura: encabezado marino con pestañas (Hoja de ruta · Mes · Plan 2030), selector de mes, 14 tarjetas KPI con chip de meta, 2 gráficos de ingreso (apilado por fuente + línea acumulada vs ritmo meta vs proyección), socios totales (área) y activaciones/bajas (barras + línea de neto), filtro de rango y "Ver datos".

| Elemento de la captura | Equivalente CRM | ¿Hoy? | Origen / requisito |
|---|---|---|---|
| Socios totales | Socios activos (clientes con ≥1 suscripción activa) | Sí, con matiz | `active_clients` por canal en `kpis`; el total unificado depende de §2.3 (doble conteo entre canales hasta reconciliar: rotular "por canal, no deduplicado") |
| Ingreso total / Recaudado pasarelas | Recaudo aceptado del mes por canal | Sí | `transactions_monthly`, `recaudo_mensual` (TCH) |
| Acumulado del año | Suma del año de recaudo | Sí | derivable de `transactions_monthly`, solo cálculo en front |
| Diferencia vs meta, ritmo meta, proyección | Meta anual y ritmo | No | requiere metas (DEC-38 recomienda "sin metas por ahora"); proyección = promedio mensual es calculable sin meta |
| Activaciones | Altas del mes | Sí | `activations_monthly` |
| Bajas / Churn | Cancelaciones, churn % | Sí, con reserva | `cancellations_monthly`, `churn_rate_pct`; definición distinta por canal (DEC-37) |
| Crecimiento neto | Altas - bajas | Sí | cálculo en front |
| Cobrabilidad | pagados / (pagados+rechazados) = 1 - tasa de rechazo | Sí | `charge_stats.py` (una sola definición); meta 70 % requiere DEC-38 |
| No cobrado | monto de cargos rechazados del mes | Sí | `rejected_charges.amount` (aclarar mezcla cargos/transacciones, UI-29) |
| Por cobrar | cargos pendientes/procesando | Sí | `pending_payments` ("cargos pendientes") |
| MRR / ARPU | tarjetas existentes | Sí | `kpis.mrr`, `kpis.arpu` |
| Etas, Donación individual | no existen como fuente | No | el CRM solo cubre recurrente por 4 canales; omitir o definir fuente |
| Socios totales en el tiempo (área) | Serie histórica de socios activos al cierre | No | endpoint nuevo (DEC-35 opción C/B); se puede aproximar acumulando altas-bajas |
| Histórico de MRR | MRR por mes | No | endpoint nuevo (DEC-35 C) |
| Apilado por fuente + meta punteada | Recaudo apilado por canal | Sí (apilado) / No (meta) | `ChannelChart kind="stacked"` ya soporta apilado; línea de referencia = nueva prop |
| Selector de mes, rango, Ver datos | Controles | Sí (front) | VIZ-03 contempla tabla alternativa |
| Pestaña Plan 2030 / Hoja de ruta | Metas multianuales | No | modelo de metas nuevo; fuera de alcance hasta DEC-38 |

Relación con el sprint VIZ: VIZ-02 (paleta/tokens) y VIZ-03 (`ChannelChart` con porcentajes, tabla alternativa, teclado) son la base; VIZ-05 (KpiCard con delta y sparkline) cubre "vs mes anterior"; VIZ-07 reemplaza los 8 componentes de MonthlyStatusChart y es exactamente el Resumen unificado; VIZ-08 deja de tener sentido como "dashboards de canales" y pasa a ser "filtro de canal del Resumen"; VIZ-04 aporta divergentes y waterfall (neto). Falta añadir a VIZ: chip de meta en KpiCard (nuevo), barra de progreso (nuevo), línea de referencia punteada y línea acumulada con proyección (nuevo en ChannelChart). Decisiones: DEC-34 mantener Recharts (cubre todo lo visto: barras apiladas, línea, área, línea de referencia); DEC-35 A (ninguno) alcanza para ~80 % del tablero; histórico de socios y de MRR piden C; DEC-36 (altas/bajas): la captura usa cian y magenta (altas/bajas), que es una tercera opción para el usuario; DEC-37 es prerrequisito para churn unificado; DEC-38 para chips "en meta/lejos de meta"; DEC-39 borrar código muerto; DEC-41 (título hero 32-40 px) aplica directo al encabezado de la captura.

## 4. Conflictos con DESIGN.md (requieren decisión del usuario)

| # | Captura | DESIGN.md | Opción recomendada |
|---|---|---|---|
| C1 | Marino #14086b en encabezado y tarjetas destacadas | Primario/sidebar teal #1a3d47 (claro) y #091418 (oscuro); "Committed teal" | **Mantener teal en sidebar** y usar el marino solo como color de serie/acento de gráficos y del encabezado de página en la tab Resumen (decisión explícita). Alternativa B: adoptar marino como nuevo primario (cambia identidad, requiere reescribir tokens y tests `designTokens.test.ts`). Recomiendo A. |
| C2 | Cian #3ecbf7, magenta, teal-azul como paleta de series | Acento #2a7a64 solo interactivo; "sin decoración"; VIZ-02 pide paleta derivada del teal validada claro/oscuro | Paleta de series (`--series-N`) con cian/magenta/teal, validada con el script de `dataviz`; acento verde sigue solo para interacción. Cierra DEC-36 junto con la decisión de altas/bajas. |
| C3 | Tarjetas KPI grises con chips y barras de progreso, "Socios totales" y "Ingreso" rellenas de color | Cards con borde sutil, sin colores laterales, sin cards anidadas; stats cards 4 columnas | Tarjeta KPI en superficie normal; solo 1-2 tarjetas hero rellenas (marino) por pantalla; chip pill con texto + dot (nunca solo color, regla ya vigente). Los chips "en meta" reutilizan semánticos success/warning/error. |
| C4 | Tipografía geométrica (parece Poppins), títulos grandes | Cabinet Grotesk/General Sans/JetBrains Mono; h1 22 px (DEC-41) | Mantener fuentes de DESIGN.md. Título hero: pregunta abierta DEC-41 (B: 32-40 px solo en el encabezado del Resumen). |
| C5 | Montos como "$101,0 MM" en fuente sans | Todos los números de BD en mono | Valores KPI en JetBrains Mono (ya lo hace KpiCard). Formato "MM" en tarjetas con el exacto en tooltip. |
| C6 | Encabezado a todo el ancho con pestañas | max-width 1160 px, sidebar 220 | Encabezado dentro del área de contenido; pestañas bajo el título. |
| C7 | Menú lateral de la captura (le gusta) | Sidebar 2 niveles por proveedor documentado en Layout y Decisions Log (2026-10-21) | **Actualizar DESIGN.md**: nueva sección Layout (nav plana por función); hoy el documento describe la navegación por canal que se quiere eliminar. Requiere aprobación porque revierte una decisión registrada. |
| C8 | Meta punteada, línea acumulada | No hay regla | Compatible. Añadir a DESIGN.md una sección "Gráficos" con tokens de serie. |

## 5. Plan de migración incremental

Reutilizar: `KpiCard` (extender con delta, chip, progreso), `ChannelKpiStrip` (base de la fila de KPIs del Resumen, con prop de canal), `ChannelChart` (+ referencia punteada, línea acumulada, apilado por canal), `features/dashboard` (`channelCharts.ts`, `OperationalAlerts`, `alertGroups`, `StatusBars`), `features/shared/kpis.ts`, `normalizeKpis`, `Sidebar` (reestructurar), `legacyRedirectPath`, `useChannelHealth`, la tabla general de suscripciones (`_general_subscriptions` + render en AppCore).
Eliminar al final: `MonthlyStatusChart.tsx` (8 componentes), `TransaccionesSuscripcionesChart` y `MonthlySimpleChart` (DEC-39), grupos de proveedor de `navigation.ts` como ítems de menú (las tablas por canal pueden seguir existiendo como detalle un tiempo), `ChannelDashboardView` como página independiente (queda como vista filtrada del Resumen), vistas `/tch/*` duplicadas una vez cubiertas por Socios/Suscripciones/Cobros, `AutomaticReport` si el Resumen lo cubre.

Prerrequisito técnico recomendado: extraer de `AppCore.tsx` (3.666 líneas, con estado y JSX inline de cada pantalla) las vistas general a `features/socios`, `features/suscripciones`, `features/cobros`, `features/resumen` antes de añadir más (hoy cualquier cambio toca el monolito).

### Tareas UX priorizadas
Convención: S ≤ 3 h de IA, M 4-8 h, L 9-16 h, XL > 16 h.

| ID | Descripción | Archivos | Esfuerzo | Riesgo | Decisión necesaria |
|---|---|---|---|---|---|
| UX-00 | Decisiones: C1-C8 de §4, DEC-34..41, nombre del menú | docs/tasks.md, DESIGN.md | S | Bajo | Usuario (bloquea todo lo visual) |
| UX-01 | Paleta de series y tokens `--series-N`, chips de meta, claro/oscuro, test de contraste | index.css, designTokens.test.ts, chartColors.ts (= VIZ-02) | S-M | Bajo | C1, C2, DEC-36 |
| UX-02 | Extender `ChannelChart`: línea de referencia, acumulado con proyección, porcentaje, tabla "Ver datos", teclado (VIZ-03) | components/ChannelChart.tsx, chartRows.ts, tests | M | Medio (tests existentes) | DEC-34 |
| UX-03 | `KpiCard` v2: delta vs período anterior, chip en meta/lejos/sin meta, barra de progreso, sparkline (VIZ-05 ampliada) | components/KpiCard.tsx(+test), formatKpi.ts | M | Bajo | DEC-38 (sin metas: chip "sin meta") |
| UX-04 | Extraer vistas de AppCore a features/* sin cambio de comportamiento | AppCore.tsx, features/* | L | Alto (regresión; AppCore sin tests) | Ninguna |
| UX-05 | Navegación nueva: sidebar plano, rutas `/resumen`, `/socios`, `/suscripciones`, `/cobros`, `/recuperador`, redirecciones legacy, actualizar DESIGN.md Layout | navigation.ts, routes.ts, Sidebar.tsx(+test), DESIGN.md | M | Medio (permisos por canal, enlaces profundos, tests de sidebar/rutas) | C7, nombres |
| UX-06 | Resumen unificado: encabezado, selector de mes, tabs, filtro de canal y rango, 14 KPIs que existen hoy, apilado por canal, altas/bajas/neto, "Ver datos" (VIZ-07 reformulada; absorbe VIZ-08) | features/resumen (nuevo), channelCharts.ts, ChannelKpiStrip.tsx, OperationalAlerts | L | Medio (cifras por canal con definiciones distintas, DEC-37) | DEC-35 A, DEC-37 |
| UX-07 | Endpoint `GET /api/v1/dashboard/general?month=&channels=` con KPIs del mes, mes anterior y series (compatible con `normalizeKpis`) | app/api/v1/routes/staging.py (`_general_dashboard`), tests | M | Medio (cache `_dashboard_cache`, rendimiento) | Ninguna |
| UX-08 | Suscripciones unificadas: promover `/central/suscripciones` a `/suscripciones`, filtros de canal/estado, panel lateral de detalle por canal, enlace a socio | features/suscripciones, `_general_subscriptions` | M | Bajo | Ninguna |
| UX-09 | Cobros unificados desde `core_charges`/`core_payments`: endpoint y tabla con estado normalizado (`charge_stats`) | nuevo router/consulta, features/cobros | L | Medio-alto (consolidación Core incompleta en TCH/Payku; PK-06 pendiente) | Qué fuente se considera cobro por canal |
| UX-10 | Socios, fase transitoria: lista unificada con canales y suscripciones activas, rotulada por RUT "no verificado", búsqueda global, ficha con paneles por canal | features/socios, `_general_clients`, `_general_client_detail` | L | Medio | Texto de la nota de población |
| UX-11 | Socios sobre Core (UUID, identidades, insignia "posible mismo socio", pestaña Identidad) | app/api/v1/routes/identity.py y staging.py, features/socios | XL | Alto (ADR-001, camino de escritura inexistente, datos personales C0) | DEC-08, gobierno del dato personal |
| UX-12 | Recuperador y Cambios de cobro bajo "Operación" (rutas generales, permisos `general.*`), filtro de canal | Sidebar, routes.ts, RecoveryPanel | S-M | Medio (migración de permisos/roles) | Ninguna (REC-04..06 dependen de TK-20 y PK-06) |
| UX-13 | Serie histórica de socios activos y MRR (endpoint nuevo) | backend + ChannelChart | M-L | Medio | DEC-35 C |
| UX-14 | Metas y pestaña Plan 2030 (modelo de metas editable, chips, ritmo meta) | modelo + migración + UI | XL | Alto (negocio) | DEC-38 B, definición de metas |
| UX-15 | Retirar código viejo: MonthlyStatusChart, vistas por canal, grupos de menú, AutomaticReport; división de bundle (VIZ-10) | varios | M | Medio | Confirmación tras VIZ-12 |
| UX-16 | Capturas y revisión visual (ver §6), incluyendo pantallas nuevas | scripts/visual/capture_sandbox.mjs | S | Bajo | Revisión del usuario (VIZ-12/USR-02) |

Tandas sugeridas (cada una cierra con tests, `tsc --noEmit`, lint y capturas):
- **T0** UX-00, UX-01 (decidir y tokens).
- **T1** UX-02, UX-03, UX-07 (bloques base; sin cambio de navegación; valor inmediato en dashboards actuales).
- **T2** UX-04, UX-08 (extraer y promover Suscripciones; riesgo controlado).
- **T3** UX-06 (Resumen nuevo), junto con UX-05 (menú); mantener rutas viejas redirigidas.
- **T4** UX-09, UX-10, UX-12 (Cobros, Socios transitorio, Operación).
- **T5** UX-11, UX-13 (identidad y series históricas; dependen de decisiones y datos).
- **T6** UX-14 (metas) y UX-15 (limpieza); UX-16 en cada tanda.

Riesgos transversales: AppCore monolítico (UX-04 primero); permisos por canal (`virtualpos.*`, `tch.*`) frente a vistas unificadas (usuario sin permiso de un canal: la tabla unificada debe filtrar server-side, no ocultar en el front); doble conteo entre canales en "Socios totales" hasta UX-11; definiciones distintas de churn/rechazo (UI-28..30, DEC-37); datos de TCH vienen de Excel semanal (mostrar "dato al <fecha>"); Payku con cobertura no certificada (nota visible); rendimiento de `_general_clients`/`_general_subscriptions` (cargan todo y paginan en memoria: con 41.883 socios hay que paginar en SQL antes de unificar); tests actuales (frontend 238, backend 1.093) asumen rutas y textos del menú actual (Sidebar.test, billing.nav.test).

## 6. Verificación con capturas (scripts/visual)
- `capture_sandbox.mjs` define las pantallas en un arreglo (nombre, ruta, `steps`) y captura 2 viewports x 2 temas, solo lectura, solo `localhost:5174`, con cero errores de consola/red como criterio (`index.json`).
- Añadir entradas: `resumen-unificado` (+ variantes mes anterior, filtro de canal, "Ver datos" abierto), `socios`, `socio-ficha-multicanal`, `suscripciones`, `cobros`, `recuperador`, `menu-lateral` (escritorio y móvil). Cambiar rutas de `dashboard-general/virtualpos/toku/payku/tch` a `/resumen?canal=...` o conservarlas hasta UX-15 para comparar antes/después.
- Procedimiento por tanda: seed `DEMO-` + backend sandbox 8001 + frontend 5174; `login` (lo hace el usuario); `capture`; comparar con las carpetas `Downloads\CRM_capturas_sandbox\2026-10-29` (antes) y la nueva (después); verificar menú lateral 220 px, sin desborde horizontal a 390 px, contraste >= 4,5:1 (test existente), y que el KPI mostrado coincide con la API (spot check contra `/dashboard/general`).
- La sandbox tiene datos sintéticos: para cifras reales de socios/identidad usar la base `crm` con lectura (decisión del usuario); no sembrar en `crm`.
- Reiniciar el backend sandbox invalida la sesión de Playwright (UI-27).

## 7. Decisiones que necesita del usuario (resumen)
1. C1/C2/C7 (colores y menú vs DESIGN.md): recomiendo mantener teal en sidebar, marino y cian/magenta solo en gráficos y encabezado del Resumen, y actualizar DESIGN.md (Layout y Decisions Log).
2. DEC-41 título hero (recomiendo B solo en el encabezado del Resumen, si quiere presencia de marca; si no, A).
3. DEC-34 A, DEC-35 A para T1-T3 (C para series históricas en T5), DEC-36 (cian/magenta como nueva opción), DEC-37 A, DEC-38 A (chips "sin meta" hasta tener metas), DEC-39 A, DEC-40 A.
4. DEC-08: destino de `reconciliacion-identidad-socios.md` (bloquea UX-11).
5. Nombre y alcance del menú (Resumen/Socios/Suscripciones/Cobros/Operación/Sistema) y si Etas/Donación individual existen como fuente (hoy no).
6. Metas 2026-2030 (quién las aporta) para UX-14.
7. Fuente canónica de "cobro" por canal para UX-09.
