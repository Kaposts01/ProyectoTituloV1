# Sesiones de validación con usuarios (MET-03)

- **Tarea:** MET-03, sección 3.11 (S7) de [`docs/tasks.md`](../tasks.md).
- **Decisión de origen:** d160 (2 a 3 sesiones con tareas guiadas; SUS como dato complementario).
- **Estado:** guion listo para usar; las sesiones se hacen en S7 (2026-11-14 a 2026-11-21).
- **Relacionado:** SEC-02 (modo demo que enmascara datos personales, ficha d199), regla 14 del [runbook de sandbox](../operations/sandbox-testing-and-decisions.md) (QA-04), [DESIGN.md](../../DESIGN.md).

## 1. Objetivo

Comprobar si las personas que van a usar el CRM a diario pueden completar sus tareas habituales sin ayuda, cuánto tardan y dónde se traban. El resultado alimenta el capítulo de calidad y resultados de la memoria (DOC-14) y la lista de correcciones de S8.

Las preguntas que responden las sesiones:

1. ¿Puede una persona del equipo encontrar un socio y entender su estado de cobro sin ayuda?
2. ¿El flujo de rechazos y recuperación se entiende y lleva a una acción concreta?
3. ¿El flujo de solicitud de cambio de cobro deja claro qué pasa después de enviarla?
4. ¿El resumen responde las preguntas de la jefatura sin abrir otra herramienta?

El SUS es un dato complementario: con 2 o 3 participantes no permite comparar con promedios de la industria, solo describir la percepción del grupo.

## 2. Participantes

| Perfil | Cantidad | Por qué |
|---|---|---|
| Jefatura del área de socios o finanzas | 1 | Usa el resumen, aprueba cambios de cobro y decide sobre recuperación. |
| Ejecutivo o ejecutiva de atención a socios | 1 o 2 | Consulta socios, revisa rechazos, usa el recuperador y exporta listados. |

Criterios:

- Personas que conocen el proceso real de cobros y socios, aunque no hayan usado el CRM.
- Que no hayan participado en el diseño de las pantallas evaluadas (evita sesgo de conocimiento previo).
- En el registro se identifican solo como P1, P2 y P3 con su perfil. No se anotan nombres, correos ni cargos exactos.

## 3. Consentimiento

Se lee en voz alta al inicio y se registra la respuesta (sí o no) en la plantilla, sin firma ni datos personales:

> Esta sesión evalúa el sistema, no a usted. Le pediremos hacer algunas tareas y pensar en voz alta mientras las hace. Puede detenerse cuando quiera y saltarse cualquier tarea. Tomaremos notas del tiempo y de lo que ocurre en pantalla. Los resultados se publican de forma agregada y anónima en un trabajo de título, identificándole solo como «participante 1, 2 o 3». La pantalla [no se graba | se graba solo porque el modo demo está encendido y no muestra datos personales]. ¿Está de acuerdo en participar?

Reglas:

- Si la persona no acepta, la sesión no se hace y no se registra nada.
- La grabación de pantalla es opcional y solo se permite bajo la regla de datos de la sección 4. El audio no se graba.
- Las notas se guardan fuera del repositorio hasta anonimizarlas; al repositorio solo llega el resumen agregado.

## 4. Regla de datos (obligatoria)

Las sesiones se hacen en uno de estos dos ambientes y en ningún otro:

| Opción | Ambiente | Condición | Grabación de pantalla |
|---|---|---|---|
| A (preferida) | Producción local (`crm`) | SEC-02 encendido y verificado antes de empezar (ver la checklist de la sección 9) | Permitida solo si se verificó que ninguna pantalla del recorrido muestra RUT, nombre, correo o teléfono en claro |
| B | Sandbox (`crm_sandbox`) | Las tareas apuntan solo a filas sintéticas `DEMO-`, `TEST` o «AmigoPrueba» | No se graba. `crm_sandbox` puede tener datos personales reales (QA-04, regla 14 del runbook); una búsqueda libre podría mostrarlos |

Además:

- Nunca se graban pantallas, ni se toman capturas, ni se copian extractos con datos personales.
- Los CSV de la tarea de exportar se descargan a una carpeta temporal y se borran al terminar la sesión; no se adjuntan al registro.
- Si durante la sesión aparece un dato personal en claro (SEC-02 falla o se navega fuera de las filas sintéticas), se detiene la grabación, se descarta y se anota el hallazgo como P0 de privacidad.
- Hasta que SEC-02 exista (ficha d199), solo es posible la opción B, sin grabación.

## 5. Preparación

- Ambiente elegido (A o B) y checklist de la sección 9 completa.
- Usuario de prueba con el rol que corresponde al perfil (jefatura: aprobador; ejecutivo: operador). Sesión iniciada antes de que llegue la persona.
- Navegador en ventana nueva, zoom al 100 %, sin otras pestañas.
- Para la opción B: identificar de antemano los socios y suscripciones sintéticos que usa cada tarea (por ejemplo `DEMO-SUB-003`) y escribirlos en la tarjeta de la tarea.
- Cronómetro, plantilla de registro impresa o en un documento aparte y el cuestionario SUS.
- Duración total: 45 a 60 minutos (5 de introducción, 30 a 40 de tareas, 5 de SUS, 5 a 10 de conversación final).

## 6. Tareas guiadas

Cada tarea se entrega en una tarjeta con el escenario, sin nombrar menús ni botones. El moderador no ayuda salvo que la persona lo pida o lleve 2 minutos sin avanzar; en ese caso da una pista y la anota como «ayuda».

Las tareas 1 a 5 y 8 aplican a todos los perfiles; la 6 es para ejecutivos y la 7 para jefatura. Si el tiempo no alcanza, se omite la 8.

| N.º | Escenario que se lee | Éxito cuando | Pantallas implicadas | Tiempo objetivo |
|---|---|---|---|---|
| T1 | «Un socio llama preguntando si su aporte de este mes se cobró. Busque al socio [identificador sintético o enmascarado] y diga en qué estado está su suscripción y cuándo fue su último cobro.» | Dice el estado y la fecha correctos | Buscador, Clientes consolidados, ficha del socio | 2 min |
| T2 | «Queremos saber cuántos cobros fueron rechazados este mes y cuál es el motivo más frecuente.» | Da la cifra y el motivo que muestra el CRM | Resumen, Cobros, filtro de rechazados | 3 min |
| T3 | «De los socios con cobros rechazados en VirtualPOS, elija uno que se pueda recuperar y diga qué haría con él.» | Llega al recuperador, identifica un socio recuperable y nombra la acción que ofrece la pantalla | Recuperador VirtualPOS | 4 min |
| T4 | «Un socio pidió cambiar el monto de su aporte. Deje registrada la solicitud de cambio de cobro.» (opción A: no se confirma el envío; opción B: se envía sobre una suscripción `DEMO-`) | Abre «Nueva solicitud», completa los campos y llega al paso de confirmar | Cambios de cobro, diálogo Nueva solicitud | 4 min |
| T5 | «Revise el resumen general y cuénteme cómo van las suscripciones activas y la baja (churn) del último mes respecto del anterior.» | Lee correctamente los KPI y la tendencia del gráfico | Resumen general, tarjetas KPI, gráficos | 3 min |
| T6 (ejecutivos) | «Necesita enviar a finanzas el listado de suscripciones activas de un canal. Expórtelo.» | Descarga el CSV con el filtro pedido | Suscripciones consolidadas, botón Exportar | 2 min |
| T7 (jefatura) | «Hay una solicitud de cambio de cobro pendiente. Revísela y decida si la aprobaría; no la confirme.» | Encuentra la solicitud, lee el detalle y las advertencias y llega al diálogo de aprobar o rechazar | Cambios de cobro: Pendientes, detalle, diálogo | 3 min |
| T8 | «Un socio pidió darse de baja. Encuentre dónde se ve el estado de esa solicitud.» | Llega a Bajas y lee el estado de una solicitud | Bajas de suscripciones | 2 min |

En la opción A (producción local) ninguna tarea confirma escrituras: T4 y T7 terminan en el diálogo, sin enviar.

## 7. Métricas por tarea

| Métrica | Cómo se mide | Valores |
|---|---|---|
| Éxito | Criterio de la columna «Éxito cuando» | 1 = completa sin ayuda; 0,5 = completa con ayuda; 0 = no completa o abandona |
| Tiempo | Desde que termina de leer el escenario hasta que da la respuesta o abandona | Segundos; tope de 2 veces el tiempo objetivo |
| Errores | Acciones que la alejan del objetivo y debe deshacer (menú equivocado, filtro equivocado, lectura incorrecta de una cifra) | Conteo |
| Ayuda | Pistas que dio el moderador | Conteo; cualquier ayuda baja el éxito a 0,5 |
| Comentario | Lo que dijo al pensar en voz alta y que explica una traba | Texto breve, sin datos personales |

Resumen por tarea (para la memoria): tasa de éxito media, tiempo mediano, errores totales y número de ayudas. Con 2 o 3 participantes se informan los valores individuales junto a la media; no se calculan intervalos.

## 8. Cuestionario SUS en español

Se entrega al terminar las tareas. Escala de 1 (totalmente en desacuerdo) a 5 (totalmente de acuerdo). Se responden todas las preguntas; si alguna queda en blanco se marca 3.

| N.º | Afirmación | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|---|
| 1 | Creo que me gustaría usar este sistema con frecuencia. | ☐ | ☐ | ☐ | ☐ | ☐ |
| 2 | Encontré el sistema innecesariamente complejo. | ☐ | ☐ | ☐ | ☐ | ☐ |
| 3 | Pensé que el sistema era fácil de usar. | ☐ | ☐ | ☐ | ☐ | ☐ |
| 4 | Creo que necesitaría el apoyo de una persona técnica para poder usar este sistema. | ☐ | ☐ | ☐ | ☐ | ☐ |
| 5 | Encontré que las distintas funciones del sistema estaban bien integradas. | ☐ | ☐ | ☐ | ☐ | ☐ |
| 6 | Pensé que había demasiadas inconsistencias en el sistema. | ☐ | ☐ | ☐ | ☐ | ☐ |
| 7 | Imagino que la mayoría de las personas aprendería a usar este sistema muy rápido. | ☐ | ☐ | ☐ | ☐ | ☐ |
| 8 | Encontré el sistema muy engorroso de usar. | ☐ | ☐ | ☐ | ☐ | ☐ |
| 9 | Me sentí con mucha confianza al usar el sistema. | ☐ | ☐ | ☐ | ☐ | ☐ |
| 10 | Necesité aprender muchas cosas antes de poder empezar a usar este sistema. | ☐ | ☐ | ☐ | ☐ | ☐ |

### Cálculo

1. Preguntas impares (1, 3, 5, 7, 9): aporte = respuesta − 1.
2. Preguntas pares (2, 4, 6, 8, 10): aporte = 5 − respuesta.
3. Suma de los 10 aportes (entre 0 y 40) × 2,5 = puntaje SUS (entre 0 y 100).

Ejemplo: respuestas 4, 2, 4, 1, 4, 2, 5, 2, 4, 2 → aportes 3, 3, 3, 4, 3, 3, 4, 3, 3, 3 = 32 → 32 × 2,5 = **80**.

Lectura (referencia habitual de la literatura, Bangor y otros, 2009): 68 es el promedio; sobre 80 es bueno; bajo 50 indica problemas serios. Con 2 o 3 participantes se informan los puntajes individuales y la media, sin afirmar que el sistema está «sobre el promedio» como conclusión estadística.

## 9. Checklist antes de cada sesión

- [ ] Consentimiento leído y aceptado (registrar sí o no).
- [ ] Ambiente: opción A con SEC-02 encendido, u opción B con solo filas sintéticas.
- [ ] Opción A: se recorrieron todas las pantallas de T1 a T8 con SEC-02 encendido y ninguna mostró RUT, nombre, correo o teléfono en claro (incluye el CSV de T6).
- [ ] Opción B: grabación apagada; identificadores `DEMO-` anotados en las tarjetas.
- [ ] Usuario de prueba con el rol correcto; sesión iniciada.
- [ ] Carpeta temporal para el CSV de T6, que se borra al terminar.
- [ ] Cronómetro, plantilla y cuestionario SUS listos.

## 10. Plantilla de registro

### 10.1 Registro por sesión

```
Sesión: S1 | Fecha: AAAA-MM-DD | Participante: P1 | Perfil: jefatura / ejecutivo
Ambiente: A (producción local, SEC-02) / B (sandbox, filas DEMO)
Consentimiento: sí | Grabación: no / sí (opción A verificada)
Moderador: [rol] | Observador: [rol]

| Tarea | Éxito (0 / 0,5 / 1) | Tiempo (s) | Errores | Ayudas | Comentario |
|---|---|---|---|---|---|
| T1 | | | | | |
| T2 | | | | | |
| ... | | | | | |

SUS: respuestas [ , , , , , , , , , ] → puntaje: __
Comentarios finales (sin datos personales):
```

### 10.2 Registro de hallazgos priorizados

Cada problema observado se anota una vez, aunque lo vean varios participantes (se suma la frecuencia).

| ID | Tarea | Pantalla | Descripción del problema | Frecuencia (n.º de participantes) | Severidad | Prioridad | Propuesta | Tarea en `tasks.md` |
|---|---|---|---|---|---|---|---|---|
| H-01 | | | | | | | | |

Severidad:

| Nivel | Criterio |
|---|---|
| Crítica | Impide completar la tarea o expone un dato personal |
| Alta | Completa solo con ayuda o con errores que llevan a una decisión equivocada (cifra mal leída) |
| Media | Completa sin ayuda pero con demora o dudas visibles |
| Baja | Comentario estético o preferencia sin efecto en la tarea |

Prioridad:

| Prioridad | Regla | Destino |
|---|---|---|
| P0 | Severidad crítica, o alta con frecuencia ≥ 2 | Se corrige antes de la demo aunque sea después del congelamiento (d158 admite defectos que afecten la demo o los datos) |
| P1 | Alta con frecuencia 1, o media con frecuencia ≥ 2 | Corrección en S8 si cabe; si no, trabajo futuro |
| P2 | Media con frecuencia 1, o baja | Trabajo futuro documentado en la memoria |

## 11. Entregables

- Registro de cada sesión, anonimizado (P1 a P3), fuera del repositorio.
- Resumen agregado para la memoria: tabla de métricas por tarea, puntajes SUS y hallazgos priorizados.
- Hallazgos P0 y P1 convertidos en filas de `docs/tasks.md`.

Definición de hecho (sección 3.11): sesiones hechas con hallazgos priorizados.
