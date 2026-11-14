# Revisiones del usuario y plan de UX-16 (S7)

- **Tareas:** USR-02, USR-03, VIZ-12 y UX-16, sección 3.11 (S7) de [`docs/tasks.md`](../tasks.md).
- **Estado:** checklists listas; las revisiones las hace el usuario en S7 (2026-11-14 a 2026-11-21).
- **Manda en lo visual:** [DESIGN.md](../../DESIGN.md). Si un ítem de esta lista contradice DESIGN.md, gana DESIGN.md y se anota la contradicción.
- **Regla de datos:** ver la sección 1. Ninguna captura ni CSV con datos personales.

Cómo usar este documento: se marca cada casilla al cumplirse el criterio de aceptación. Lo que no se cumple se anota en la tabla de hallazgos de la sección 6 con su prioridad y se enlaza a una fila de `tasks.md`.

## 1. Regla de datos para todas las revisiones

- **Sandbox (`crm_sandbox`):** puede tener datos personales reales (QA-04, regla 14 del [runbook](../operations/sandbox-testing-and-decisions.md)). Se revisa en el navegador, pero las capturas solo pueden mostrar filas sintéticas `DEMO-`, `TEST` o «AmigoPrueba». Si una pantalla mezcla filas sintéticas con otras, no se captura, o se captura filtrada de modo que solo queden las sintéticas.
- **Producción local (`crm`):** se puede capturar solo con SEC-02 (modo demo) encendido y verificado. Hasta que SEC-02 exista (ficha d199), no se toman capturas de producción local.
- **Portal de VirtualPOS (USR-03):** las cifras agregadas (conteos, montos totales) se pueden anotar; no se copian listados ni capturas del portal con datos de socios.
- **CSV:** se descargan a una carpeta temporal y se borran al terminar; no se adjuntan a informes, fichas ni PR.

## 2. USR-02: revisión visual en navegador

Alcance (fila USR-02): Sprints 3 y 4, bandeja de cambios de cobro y pestaña Renovaciones. Se hace en el sandbox sobre las filas `DEMO-` sembradas por UI-27, en tema claro y oscuro, en escritorio (1440 px) y móvil (390 px).

| ✓ | Ítem | Dónde | Criterio de aceptación |
|---|---|---|---|
| ☐ | Franja de sandbox | Todas las pantallas | Se ve una franja que identifica el ambiente sandbox, legible en ambos temas y sin tapar contenido. |
| ☐ | Tema oscuro | Todas las pantallas del recorrido | No quedan superficies claras sueltas, textos ilegibles ni íconos invisibles; la paleta es la del modo oscuro de DESIGN.md (no una inversión). |
| ☐ | Barra lateral | Escritorio | Azul marino en ambos temas (#111727 claro, #0a0f1c oscuro); el ítem activo se distingue sin depender solo del color. |
| ☐ | Menú móvil | 390 px | Abre con la hamburguesa; Esc y clic fuera lo cierran; el foco queda dentro mientras está abierto; buscador e indicador de salud miden 44 px de alto. |
| ☐ | Puntos de salud de canal | Barra lateral | El punto de cada canal contrasta al menos 3:1 con el fondo de la barra en ambos temas y su estado también se dice en texto o tooltip. |
| ☐ | Gráficos del resumen | `/central/resumen`, `/virtualpos/resumen` | Cada gráfico tiene título que responde una pregunta, ejes legibles y leyenda; las cifras usan JetBrains Mono. (El detalle va en VIZ-12.) |
| ☐ | Recuperador VirtualPOS | `/virtualpos/recuperador-socios` | La lista carga, los filtros responden y la acción por socio es clara; montos y fechas en JetBrains Mono. |
| ☐ | Descarga real del CSV | Recuperador y Suscripciones consolidadas | El CSV se descarga, abre en una planilla con columnas y acentos correctos, y respeta el filtro aplicado. Se borra al terminar. |
| ☐ | Bandeja de cambios de cobro: Pendientes | `/general/cambios-de-cobro` | La tabla lista las solicitudes `DEMO-`; el detalle muestra estado, advertencias y comentarios. |
| ☐ | Diálogos Aprobar, Rechazar y Nueva solicitud | Misma pantalla | Abren con el foco en el primer campo, piden comentario cuando corresponde, Esc cierra sin enviar. No se confirma ninguno. |
| ☐ | Historial | Misma pantalla, pestaña Historial | Solicitudes ejecutadas y fallidas muestran su resultado (por ejemplo el código de error en mono 11 px). |
| ☐ | Renovaciones | Misma pantalla, pestaña Renovaciones | La pestaña carga y su contenido se entiende sin explicación. |
| ☐ | Arreglos UI-22 a UI-26 | Según cada fila de `tasks.md` | Cada arreglo se ve como describe su fila. |

USR-02 queda hecha cuando todas las casillas están marcadas o los incumplimientos tienen fila en `tasks.md`.

## 3. USR-03: verificar KPI-01 y CHART-01 contra VirtualPOS

Requiere acceso humano al portal de VirtualPOS staging. Se compara el mismo periodo y la misma fecha de corte en ambos lados; se anota la hora de la última sincronización del CRM (panel del scheduler) para explicar diferencias por datos más recientes en el portal.

Tolerancia: las cifras de conteo deben coincidir exactamente; los montos, al peso. Si no coinciden, se anota la diferencia y se investiga antes de dar el ítem por malo (puede ser una sincronización pendiente o una regla de negocio distinta, como qué cuenta como «activa»).

| ✓ | Indicador | En el CRM | En VirtualPOS | Criterio de aceptación |
|---|---|---|---|---|
| ☐ | Suscripciones activas | Tarjeta KPI, `/virtualpos/resumen` | Listado de suscripciones filtrado por activas | Mismo conteo a la misma fecha de corte. |
| ☐ | MRR | Tarjeta KPI | Suma de montos mensuales de las suscripciones activas | Mismo monto, o diferencia explicada por la regla de cálculo documentada. |
| ☐ | ARPU | Tarjeta KPI | MRR ÷ suscripciones activas (cálculo a mano) | Coincide con el cálculo hecho a partir de las dos cifras anteriores. |
| ☐ | Churn mensual | Tarjeta KPI | Bajas del mes ÷ activas al inicio del mes (cálculo a mano) | Coincide con la definición unificada de churn (d109). |
| ☐ | Cargos rechazados | Tarjeta KPI (rótulo «Cargos rechazados») | Listado de cargos del mes con estado rechazado | Mismo conteo en el mes. |
| ☐ | CHART-01: suscripciones activas acumuladas | Gráfico del resumen VirtualPOS | Conteo de activas al cierre de 3 meses elegidos | Coinciden los 3 puntos revisados. |
| ☐ | CHART-01: cargos mensuales apilados | Gráfico del resumen VirtualPOS | Cargos por estado en 3 meses elegidos | Coinciden los totales por estado de los 3 meses. |
| ☐ | CHART-01: altas y bajas | Gráfico del resumen VirtualPOS | Altas y bajas en 3 meses elegidos | Coinciden los 3 meses. |

Registro (solo cifras agregadas, sin datos de socios):

| Indicador | Periodo | CRM | VirtualPOS | Diferencia | Explicación |
|---|---|---|---|---|---|
| | | | | | |

USR-03 queda hecha cuando las ocho filas están verificadas; entonces KPI-01 pasa a «Completada y verificada».

## 4. VIZ-12: revisión visual de los gráficos

Alcance (fila VIZ-12): todos los gráficos del sistema VIZ, en ambos temas y en móvil. Se revisan los resúmenes general y por canal (`/central/resumen`, `/virtualpos/resumen`, `/toku/resumen`, `/payku/resumen`, `/tch/resumen`). En el sandbox, los resúmenes muestran solo agregados, por lo que se pueden capturar si ningún tooltip ni tabla anexa muestra datos personales.

| ✓ | Ítem | Criterio de aceptación |
|---|---|---|
| ☐ | Una pregunta por gráfico | El título del gráfico (22 px, d109) formula o responde una pregunta concreta; no hay dos gráficos que respondan lo mismo en la misma pantalla. |
| ☐ | Tipo adecuado | Tendencias en líneas o áreas, comparaciones en barras, composición en barras apiladas; ningún gráfico de torta para más de 3 categorías. |
| ☐ | Colores de series | Las series usan los tokens de DESIGN.md (`--series-N`), sin colores sueltos; el mismo concepto tiene el mismo color en todas las pantallas. |
| ☐ | Contraste de marcas | Líneas, barras y puntos contrastan al menos 3:1 con el fondo en ambos temas (WCAG 1.4.11). |
| ☐ | No depender solo del color | Las series se distinguen también por leyenda, etiqueta directa o patrón. |
| ☐ | Ejes y números | Ejes rotulados, unidades visibles (CLP, %, n.º); números en JetBrains Mono; formato chileno (punto de miles, coma decimal). |
| ☐ | Porcentajes | «Crecimiento real mensual» y «Churn %» usan el componente nuevo (VIZ-06) y muestran el signo % y la base de cálculo. |
| ☐ | Tooltip | Aparece con el puntero y con el teclado (foco en el gráfico o tabla alternativa), muestra fecha y valor exacto, y no sale del área visible. |
| ☐ | Estados | Carga: esqueleto en `--surface-alt`; vacío: mensaje con acción; error: alerta inline con reintentar (tabla «Interaction States» de DESIGN.md). |
| ☐ | Tema oscuro | Rejilla, ejes y leyenda legibles; ninguna serie desaparece contra el fondo. |
| ☐ | Móvil (390 px) | El gráfico no se corta ni genera scroll horizontal de la página; la leyenda se reacomoda; las etiquetas no se superponen. |
| ☐ | Sin código muerto visible | No queda ningún gráfico con el estilo viejo (d109, DEC-39). |

VIZ-12 queda hecha cuando todas las casillas están marcadas en ambos temas y en móvil; con eso se cierra el sprint VIZ.

## 5. UX-16: capturas de estados y pasada de contraste y teclado

### 5.1 Dónde se capturan

Solo en uno de estos dos ambientes:

1. **Sandbox con datos `DEMO-`**, usando `scripts/visual/capture_sandbox.mjs` (UI-27) y revisando cada imagen antes de guardarla: si aparece una fila que no es sintética, la captura se descarta.
2. **Producción local con SEC-02 encendido y verificado**, cuando SEC-02 exista (d199).

Las capturas no se versionan si muestran listados; para la memoria se eligen las que solo tienen filas sintéticas o datos enmascarados.

### 5.2 Pantallas y estados

Cada pantalla se captura en tema claro y oscuro, escritorio y móvil, y en los estados que apliquen. Los estados vacío y error se provocan sin tocar datos: filtro sin resultados para el vacío; backend detenido o red desconectada en el navegador (herramientas de desarrollo) para el error; red lenta simulada para la carga.

| ✓ | Pantalla | Ruta | Carga | Vacío | Error | Criterio de aceptación |
|---|---|---|---|---|---|---|
| ☐ | Resumen general | `/central/resumen` | ☐ | ☐ | ☐ | Tarjetas KPI con esqueleto al cargar, «—» en mono si no hay dato, badge rojo con mensaje si falla. |
| ☐ | Resúmenes por canal | `/virtualpos/resumen`, `/toku/resumen`, `/payku/resumen`, `/tch/resumen` | ☐ | ☐ | ☐ | Igual que el resumen general; los gráficos muestran su propio estado. |
| ☐ | Clientes consolidados | `/central/clientes` | ☐ | ☐ | ☐ | Filas esqueleto; vacío con acción (limpiar filtros); error inline con reintentar. |
| ☐ | Suscripciones consolidadas | `/central/suscripciones` | ☐ | ☐ | ☐ | Igual que Clientes; el botón Exportar se deshabilita si no hay filas. |
| ☐ | Cobros | `/central/cobros` | ☐ | ☐ | ☐ | Igual que Clientes. |
| ☐ | Ficha de socio | Ficha desde Clientes | ☐ | ☐ | ☐ | Secciones sin cobros muestran un mensaje, no una tabla vacía. |
| ☐ | Recuperador VirtualPOS | `/virtualpos/recuperador-socios` | ☐ | ☐ | ☐ | Vacío positivo («sin socios por recuperar») con acción. |
| ☐ | Cambios de cobro (Pendientes, Historial, Renovaciones) | `/general/cambios-de-cobro` | ☐ | ☐ | ☐ | Cada pestaña con su estado; el error muestra canal y código en mono 11 px. |
| ☐ | Bajas | `/general/bajas` | ☐ | ☐ | ☐ | Igual que Clientes. |
| ☐ | Alertas operativas | Resumen | ☐ | ☐ | ☐ | Vacío no devuelve nada en blanco: «Sin alertas operativas», check verde y última sincronización. |
| ☐ | Panel del scheduler | `/admin/sincronizaciones` | ☐ | ☐ | ☐ | Botón de sincronizar con spinner y deshabilitado al cargar; toast de error con mensaje del proveedor. |
| ☐ | Administración: usuarios y aprobaciones | `/admin/usuarios` | ☐ | ☐ | ☐ | Igual que Clientes. |

Regla general (DESIGN.md): nunca un spinner de pantalla completa; los estados vacíos siempre incluyen una acción.

### 5.3 Pasada de contraste y teclado (WCAG 2.1 AA)

Se hace sobre las pantallas de 5.2. Herramientas sugeridas: inspector de contraste del navegador y navegación solo con teclado (Tab, Shift+Tab, Enter, Espacio, Esc, flechas). Las razones de contraste de los tokens ya las vigila `frontend/src/designTokens.test.ts`; esta pasada busca los casos que el test no cubre (colores fijos, estados hover y foco, superposiciones).

| ✓ | Criterio WCAG 2.1 | Qué se revisa | Criterio de aceptación |
|---|---|---|---|
| ☐ | 1.4.3 Contraste mínimo | Texto normal y texto grande en ambos temas, incluidas tarjetas KPI destacadas y badges | Texto normal ≥ 4,5:1; texto grande (≥ 18,66 px en negrita o ≥ 24 px) ≥ 3:1. |
| ☐ | 1.4.11 Contraste no textual | Bordes de campos, íconos con significado, puntos de salud, marcas de gráficos, anillo de foco | ≥ 3:1 contra el fondo adyacente. |
| ☐ | 1.4.1 Uso del color | Estados de cobro, salud de canal, series de gráficos | El significado también se transmite con texto, ícono o forma. |
| ☐ | 1.4.4 y 1.4.10 Cambio de tamaño y reflujo | Zoom al 200 % y ancho de 320 px | No se pierde contenido ni funciones; sin scroll horizontal salvo en tablas de datos. |
| ☐ | 2.1.1 Teclado | Todo el recorrido: menú, filtros, tablas, pestañas, diálogos, exportar | Todas las acciones se pueden hacer solo con teclado. |
| ☐ | 2.1.2 Sin trampas de teclado | Diálogos, menú móvil, selectores de fecha | Se puede salir siempre (Esc o Tab); el foco atrapado solo existe mientras el diálogo o el menú está abierto. |
| ☐ | 2.4.3 Orden del foco | Cada pantalla | El foco sigue el orden visual; al cerrar un diálogo vuelve al botón que lo abrió. |
| ☐ | 2.4.7 Foco visible | Todos los elementos interactivos | Anillo de foco con `--color-accent`, visible en ambos temas. |
| ☐ | 2.4.2 y 2.4.6 Títulos y encabezados | Cada pantalla | El título de la pestaña del navegador y el `h1` describen la pantalla. |
| ☐ | 3.3.1 y 3.3.2 Errores y etiquetas | Formularios de nueva solicitud, aprobar, rechazar y filtros | Cada campo tiene etiqueta visible; los errores dicen qué falló y cómo corregirlo. |
| ☐ | 4.1.2 Nombre, función y valor | Pestañas, diálogos, botones de ícono, menú móvil | Roles ARIA correctos (`tab`, `dialog`), botones de ícono con nombre accesible. |
| ☐ | 4.1.3 Mensajes de estado | Toasts de sincronización, resultado de exportar, carga de tablas | Se anuncian a lectores de pantalla sin mover el foco (`role="status"` o `aria-live`). |

UX-16 queda hecha cuando las capturas de 5.2 existen en los ambientes permitidos y la pasada de 5.3 no tiene incumplimientos abiertos de prioridad P0 o P1.

## 6. Hallazgos

| ID | Revisión (USR-02, USR-03, VIZ-12, UX-16) | Pantalla | Descripción | Criterio incumplido | Prioridad (P0, P1, P2) | Fila en `tasks.md` |
|---|---|---|---|---|---|---|
| R-01 | | | | | | |

Prioridades: P0 bloquea la demo o expone un dato personal (se corrige aunque sea después del congelamiento, d158); P1 afecta una tarea o un criterio WCAG AA (S8 si cabe); P2 es estético (trabajo futuro).

## 7. Qué queda bloqueado por SEC-02

- Capturas de producción local para UX-16 y para la memoria.
- Revisión de estados sobre datos reales (volumen real, nombres largos), que solo se puede hacer con el modo demo encendido.
- Todo lo que hoy se hace en el sandbox se limita a las filas sintéticas `DEMO-`, `TEST` o «AmigoPrueba».
