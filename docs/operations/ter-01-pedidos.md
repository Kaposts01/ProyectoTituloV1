# TER-01: pedidos finales a terceros con fecha límite

> **Estado:** borradores listos para que el usuario los envíe (S6). El equipo solo redacta: nada de este documento se
> ha enviado a ningún proveedor.
> **Fecha límite de respuesta pedida:** miércoles 19 de noviembre de 2026.
> **Corte (d154):** cierre de S7, viernes 21 de noviembre de 2026.
> **Fuentes:** `docs/tasks.md` (TER-01, §3.9 a §3.12, §5: DEC-01, DEC-02, DEC-03, DEC-09, DEC-10, DEC-26), fichas de la
> Bandeja d167 a d173, d174 a d181, d184, d186, d190 y d191; documentación de cada canal en `docs/integrations/`.

## Instrucciones para el usuario antes de enviar

1. Revisar que el destinatario sea el canal de soporte oficial de cada proveedor (el mismo usado en consultas
   anteriores) y escribir el saludo con el nombre de la persona de contacto si se conoce.
2. Los correos no llevan llaves, tokens, RUT, correos de socios ni identificadores de suscripciones reales. Si el
   proveedor pide un ejemplo concreto, responder con un identificador de **sandbox** o de prueba, nunca de producción.
3. Firmar con la firma institucional habitual (no está incluida en los borradores).
4. Registrar la fecha de envío en la fila TER-01 de `docs/tasks.md` y en la ficha de la Bandeja correspondiente.
5. **VirtualPOS:** la consulta de la ficha d190 (agotamiento de `num_charges` con `automatic_renewal = F`, valor por
   defecto, cambio sin pedir tarjeta y cargos futuros en `GET /v3/charges`) **ya fue enviada**; el borrador de abajo no
   la repite, solo la menciona como antecedente.

---

## Borrador 1: Payku

**Asunto:** Activación de sandbox y consultas técnicas sobre la API (respuesta solicitada antes del 19/11/2026)

> Estimado equipo de soporte de Payku:
>
> Junto con saludar, les escribimos en relación con la integración de nuestra organización con la API de Payku
> (suscripciones, transacciones y conciliación). Estamos cerrando una etapa del proyecto y necesitamos resolver las
> siguientes consultas. Les agradeceríamos una respuesta **a más tardar el miércoles 19 de noviembre de 2026**; lo que
> no alcancemos a confirmar quedará documentado como trabajo futuro.
>
> Cada pregunta indica brevemente por qué la necesitamos.
>
> **A. Ambiente de pruebas**
>
> 1. **Activación del sandbox.** ¿Pueden habilitar para nuestra cuenta el ambiente de pruebas (`des.payku.cl`) y
>    confirmarnos cómo generar sus tokens público y privado desde el panel?
>    *Por qué:* todas las validaciones siguientes requieren probar sin afectar datos reales.
> 2. **Host de pruebas vigente.** En distintas fuentes aparecen dos hosts de prueba: `des.payku.cl` y
>    `testing-apirest.payku.cl`. ¿Cuál es el vigente para la API REST, y el otro sigue operativo o está obsoleto?
>    *Por qué:* nuestro sistema rechaza por diseño cualquier host que no reconozca como sandbox; necesitamos fijar el
>    correcto.
>
> **B. Firma de las solicitudes (`Sign`)**
>
> 3. **`&` final sin parámetros.** En una solicitud sin parámetros (por ejemplo `GET /api/suplan/plans`), ¿la cadena
>    que se firma termina en `&` (`%2Fapi%2Fsuplan%2Fplans&`), como en los ejemplos PHP y JavaScript, o sin `&`?
>    *Por qué:* los ejemplos oficiales y otras referencias difieren y una firma errónea produce rechazos (Q-01).
> 4. **`Sign` en endpoints que no lo exigen.** ¿La API acepta, ignora o rechaza el encabezado `Sign` cuando se envía en
>    endpoints que no lo requieren (transacciones, conciliación, catálogos)?
>    *Por qué:* nuestro cliente lo envía en todas las rutas por uniformidad (Q-02).
> 5. **Valores booleanos y nulos en la firma.** Cuando el cuerpo firmado contiene un booleano (`true`/`false`) o un
>    valor nulo, ¿cómo debe representarse en la cadena firmada (`1`, `true`, vacío u omitido)? ¿Y el carácter `~`
>    debe codificarse como `%7E`?
>    *Por qué:* los ejemplos PHP y JavaScript difieren en este punto y hoy evitamos enviar esos valores.
>
> **C. Consultas y filtros**
>
> 6. **Filtros de fecha en suscripciones (V3).** En `GET /api/sususcriptionv3`, ¿sobre qué fecha filtran `date_init` y
>    `date_end` (creación, inicio o último cobro)? ¿Son inclusivos y existe un rango máximo?
>    *Por qué:* define cómo hacemos la carga inicial y las lecturas incrementales (Q-11).
> 7. **Filtros de fecha en transacciones.** Al consultar `GET /api/transaction` con `date_init` y `date_end` obtenemos
>    cero resultados incluso para rangos que sí contienen transacciones; sin filtros recibimos solo las recientes.
>    ¿Cuál es el formato de fecha esperado y cómo se obtiene el historial completo (paginación, rango máximo o una
>    exportación)?
>    *Por qué:* sin esto no podemos certificar que nuestro historial de transacciones está completo.
> 8. **Filtro por estado de suscripción.** ¿El filtro correcto es `?<estado>=true` (por ejemplo `?active=true`) o
>    `?status=<estado>`? ¿Se pueden combinar varios estados en una misma consulta?
>    *Por qué:* la documentación muestra la primera forma y queremos usar la forma soportada.
>
> **D. Cobros de suscripción, transacciones y conciliación**
>
> 9. **Cobros de suscripción en transacciones y conciliación.** ¿Los cobros automáticos de una suscripción aparecen en
>    `GET /api/transaction` y en la conciliación? ¿Con qué `payment_key` u `order`? ¿Se pueden consultar con
>    `GET /api/transaction/{id}`?
>    *Por qué:* define cómo enlazamos cada cobro con su pago y con la liquidación (Q-06).
> 10. **Clave estable de un cobro.** ¿Cuál es el identificador estable de un cobro de suscripción? ¿El arreglo
>     `paid[].transactions[]` de V3 trae siempre el número de transacción? ¿`paid_number` y `try_number` se repiten
>     entre reintentos?
>     *Por qué:* lo usamos para no duplicar cobros al sincronizar (Q-08).
> 11. **Formato de `transaction_id` en conciliación.** En la conciliación el identificador de transacción aparece con
>     formato de texto tipo hash, mientras que en `/api/transaction` es un número entero. ¿Cómo se relacionan ambos
>     identificadores y cuál debemos usar para cruzar una línea de conciliación con su transacción?
>     *Por qué:* hoy no podemos cruzar ambas fuentes de forma determinista.
> 12. **Primer aporte del alta.** El primer pago de un socio, hecho con `POST /api/transaction` antes de crear la
>     suscripción, ¿aparece en transacciones y conciliación igual que un pago único? ¿Tiene algún campo que lo distinga
>     de los cobros recurrentes? ¿Puede usarse `POST /api/sutransaction` sobre una suscripción activa?
>     *Por qué:* evita contar dos veces el primer mes en nuestros reportes (Q-33).
>
> **E. Planes y enrolamiento**
>
> 13. **Plan de monto variable.** En un plan de monto variable, ¿el primer cobro se realiza al activar la suscripción o
>     a partir del mes siguiente?
>     *Por qué:* si cobra al activarse, el primer aporte se duplicaría (Q-27).
> 14. **Nuevo enlace de inscripción.** ¿`POST /api/suinscriptionscards` genera una URL nueva para una suscripción que
>     sigue en estado `register` (inscripción no completada)? ¿La URL anterior deja de funcionar?
>     *Por qué:* lo necesitamos para reenviar el enlace a quien no terminó su inscripción (Q-29).
>
> Quedamos atentos a su respuesta. Si alguna consulta requiere una reunión breve, con gusto la coordinamos.
>
> Saludos cordiales,

---

## Borrador 2: Toku

**Asunto:** Consultas pendientes sobre pruebas, webhooks, reportes y versión de la API (respuesta solicitada antes del 19/11/2026)

> Estimado equipo de soporte de Toku:
>
> Junto con saludar, agradecemos sus respuestas anteriores sobre el ambiente, los estados de los medios de pago, los
> webhooks, los reportes y la configuración de flujos, que ya incorporamos a nuestra documentación. Nos quedan algunas
> consultas para cerrar la integración en esta etapa. Les agradeceríamos una respuesta **a más tardar el miércoles 19
> de noviembre de 2026**; lo que no alcancemos a confirmar quedará documentado como trabajo futuro.
>
> 1. **Rechazos de prueba con tarjeta.** Entendemos que no existen tarjetas ni montos de prueba para simular rechazos
>    TE, PE o UE. ¿Existe algún otro mecanismo para obtener, con llaves de prueba, una transacción en estado
>    `temporary_failed` o `permanent_failed` (por ejemplo, un cliente marcado de prueba o una acción desde el
>    backoffice)? Si no existe, ¿podrían compartirnos ejemplos anonimizados de las respuestas de la API y del webhook
>    para cada tipo de rechazo?
>    *Por qué:* nuestro clasificador de rechazos y la detección de socios recuperables solo se han probado con datos
>    históricos.
> 2. **Retención y reenvío de webhooks.** ¿Por cuánto tiempo conserva Toku los eventos de webhook y el registro de sus
>    entregas? ¿Existe un endpoint para listar eventos pasados o pedir el reenvío de un evento que no recibimos (por
>    ejemplo, tras una caída de nuestro servidor)?
>    *Por qué:* define cuánto tiempo puede estar caído nuestro receptor sin perder cambios.
> 3. **Permisos de la API de reportes.** Para usar `POST /reports/{entity}` con nuestra organización, ¿qué permisos o
>    habilitaciones necesitamos y cómo se solicitan? ¿Pueden indicarnos qué entidades de reporte tiene habilitadas hoy
>    nuestra organización?
>    *Por qué:* queremos reemplazar la descarga manual semanal de reportes por una descarga automática.
> 4. **Checkout Default para inscripción.** Al abrir una sesión de checkout, `id_checkout` acepta el checkout Default de
>    un flujo. ¿Ese checkout Default sirve para `mode: ENROLLMENT` (inscripción de tarjeta o PAC sin cobro), o solo
>    para `PAYMENT`? Si no sirve, ¿qué debe configurarse en la webapp para tener un flujo de inscripción?
>    *Por qué:* el alta de socios y el cambio de tarjeta dependen de tener un flujo de inscripción válido.
> 5. **Dominio del checkout.** ¿Desde qué dominio o dominios se sirven las páginas de checkout (inscripción y pago) en
>    producción?
>    *Por qué:* validamos el origen de los enlaces que enviamos a los socios contra una lista de dominios permitidos.
> 6. **Versión de la API (`x-api-version`).** Hoy no enviamos `x-api-version` y recibimos la versión asociada a la
>    fecha de creación de la organización. ¿Cuál es esa versión para nuestra organización? ¿Recomiendan fijar
>    explícitamente una versión (por ejemplo `2026-10-08`) y cuál es la política de soporte de versiones antiguas?
>    *Por qué:* fijarla evita que un cambio de contrato altere los datos que leemos.
> 7. **Filtro de fechas en transacciones.** En `GET /transactions`, ¿los parámetros `start_date` y `end_date` filtran
>    por `transaction_date` o por `initialization_date`? ¿Son inclusivos?
>    *Por qué:* define la ventana del proceso diario de seguimiento de cobros.
>
> Quedamos atentos a su respuesta.
>
> Saludos cordiales,

---

## Borrador 3: VirtualPOS

**Asunto:** Consultas técnicas sobre pruebas, webhooks de cargos y comportamiento del sandbox (respuesta solicitada antes del 19/11/2026)

> Estimado equipo de soporte de VirtualPOS:
>
> Junto con saludar, y como complemento de nuestra consulta reciente sobre `num_charges` y `automatic_renewal` (que
> no repetimos aquí), les escribimos con algunas preguntas adicionales para cerrar las pruebas de nuestra integración
> con la API v3 de suscripciones y cargos. Les agradeceríamos una respuesta **a más tardar el miércoles 19 de noviembre
> de 2026**; lo que no alcancemos a confirmar quedará documentado como trabajo futuro.
>
> 1. **Tarjetas de prueba con rechazo.** ¿Existen en el sandbox tarjetas de prueba que produzcan un cargo rechazado
>    (idealmente con distintos motivos: fondos insuficientes, tarjeta bloqueada, tarjeta vencida)? ¿Y alguna forma de
>    probar el cambio de tarjeta de una suscripción activa?
>    *Por qué:* nuestras pruebas de contrato de cobros, rechazos y cambio de tarjeta están detenidas por esta falta.
> 2. **Firma de los webhooks de cargos.** Los webhooks de payouts traen el encabezado `Signature` (HMAC-SHA256 del
>    cuerpo). ¿Los webhooks PAT de cargos (`charge_paid`, `charge_reject`) y de suscripción (`suscription_activated`,
>    `suscription_failed`) también vienen firmados? Si es así, ¿con qué encabezado y con qué secreto?
>    *Por qué:* sin firma tratamos esos avisos solo como señal y releemos todo por API; con firma podríamos validarlos.
> 3. **IPs de origen de los webhooks.** ¿Desde qué direcciones IP o rangos envía VirtualPOS los webhooks, en sandbox y
>    en producción? ¿Pueden cambiar sin aviso?
>    *Por qué:* queremos restringir el receptor a esas direcciones.
> 4. **Cargo en línea (`POST /v3/charge/online`).** ¿Este endpoint está habilitado para nuestro comercio y para
>    suscripciones de plan de monto fijo? ¿El cobro se ejecuta en el momento y su resultado (pagado o rechazado) llega
>    en la misma respuesta o hay que consultarlo después?
>    *Por qué:* evaluamos usarlo para aportes extraordinarios sin crear un cargo programado.
> 5. **Alcance del error E-086.** El catálogo describe E-086 como «El internal_code ya ha sido utilizado para autorizar
>    un cargo». En el sandbox, dos `POST /v3/charge` con el mismo `internal_code` crearon dos cargos sin error. ¿E-086
>    se aplica solo cuando el primer cargo ya fue autorizado (pagado)? ¿Existe algún mecanismo de idempotencia para la
>    creación de cargos?
>    *Por qué:* necesitamos evitar cargos duplicados si una solicitud se reintenta.
> 6. **Filtros de fecha en el listado de cargos.** En el sandbox, `charge_date_from` y `charge_date_to` en el listado de
>    cargos de una suscripción parecen ignorarse (se devuelven todos los cargos). ¿Es un comportamiento del sandbox o
>    también ocurre en producción? ¿Cuál es el formato esperado?
>    *Por qué:* define si podemos leer solo una ventana de fechas o debemos leer todo el calendario.
> 7. **Paginación.** En el sandbox, `page=0` y `limit=101` no devuelven los errores E-090 y E-091 documentados, y en
>    `GET /v3/clients` los datos de paginación vienen dentro de un objeto `pagination` y no en la raíz. ¿Cuál es el
>    contrato vigente en producción (página inicial, límite máximo y ubicación de los datos de paginación)?
>    *Por qué:* nuestro lector usa `page` desde 1 y `limit` hasta 100, y queremos confirmar que es lo correcto.
>
> Quedamos atentos a su respuesta.
>
> Saludos cordiales,

---

## Tabla: pregunta → tarea del CRM afectada

| Proveedor | N.º | Tema | Referencia | Tareas del CRM afectadas |
| --- | --- | --- | --- | --- |
| Payku | 1 | Activación del sandbox | DEC-10, USR-04 | VAL-PK-01, PK-01, PK-05, BLQ-PK-01, RJ-08, RT-10 |
| Payku | 2 | Host de pruebas vigente | d184 | VAL-PK-01 (guardas de `PAYKU_SANDBOX_BASE_URL` en `app/core/config.py`) |
| Payku | 3 | `&` final en la firma | Q-01 | VAL-PK-01 (`app/integrations/payku/auth.py`) |
| Payku | 4 | `Sign` en endpoints que no lo exigen | Q-02 | VAL-PK-01 (`app/integrations/payku/client.py`) |
| Payku | 5 | Booleanos, nulos y `~` en la firma | d184 | VAL-PK-01, RT-10 (escrituras firmadas) |
| Payku | 6 | Filtros de fecha en V3 | Q-11 | PK-05, SYNC-O-06 |
| Payku | 7 | Filtros de fecha en transacciones | d184 | PK-01, PK-05, RJ-08, RJ-09, SYNC-O-06 |
| Payku | 8 | Filtro por estado | d183 (punto 3) | SYNC-O-06 |
| Payku | 9 | Cobros en transacciones y conciliación | Q-06 | VAL-PK-01, PK-05, PK-PAR-05 |
| Payku | 10 | Clave estable de un cobro | Q-08 | PK-05 (y el modelo de cargos de PK-06 ya implementado) |
| Payku | 11 | `transaction_id` hash frente a entero | d184 | PK-05, PK-PAR-08 (conciliación de reportes) |
| Payku | 12 | Primer aporte del alta | Q-33 | BLQ-PK-01, VAL-PK-01 |
| Payku | 13 | Plan de monto variable | Q-27 | BLQ-PK-01 |
| Payku | 14 | Nuevo enlace de inscripción | Q-29 | VAL-PK-01 (link de inscripción, caso de alta pendiente) |
| Toku | 1 | Rechazos de prueba | TK-15, DEC-09 | TK-15, VAL-TK-01, USR-05 |
| Toku | 2 | Retención y reenvío de webhooks | d171 | RT-03, TK-12 |
| Toku | 3 | Permisos de `POST /reports` | d172 | TK-PAR-11, USR-09, SYNC-D-15 |
| Toku | 4 | Checkout Default para ENROLLMENT | DEC-01, d173 | BLQ-TK-01 |
| Toku | 5 | Dominio del checkout | DEC-02 | BLQ-TK-01 (lista de hosts permitidos) |
| Toku | 6 | Fijar `x-api-version` | d191 | VAL-TK-01 |
| Toku | 7 | Filtro de fechas en `GET /transactions` | DEC-03 | VAL-TK-01, SYNC-D-15 |
| VirtualPOS | 1 | Tarjetas de prueba con rechazo | DEC-09, USR-05 | BILL-11, VAL-VP-01, CT-01, BILL-12 |
| VirtualPOS | 2 | Firma de webhooks de cargos | d186 | Receptor de webhooks VP (`app/api/v1/routes/webhooks_virtualpos.py`) |
| VirtualPOS | 3 | IPs de origen | d186 | Receptor de webhooks VP; operación (`docs/operations/webhooks-runbook.md`) |
| VirtualPOS | 4 | `POST /v3/charge/online` | d186 | BILL-11 (alcance), trabajo futuro de aportes extraordinarios |
| VirtualPOS | 5 | Alcance de E-086 | VP-C07 | BILL-11, CT-01 (idempotencia de cargos gestionados) |
| VirtualPOS | 6 | Filtros de fecha en cargos | VP-C26 | CT-01, VAL-VP-01 |
| VirtualPOS | 7 | Paginación | VP-C14, VP-C15 | CT-01, VAL-VP-01 |

Recuento: Payku 14 preguntas, Toku 7 y VirtualPOS 7 (28 en total).

## Regla de corte (d154)

Las preguntas que no tengan respuesta al **cierre de S7 (2026-11-21)** se dan por no respondidas. Cada tarea afectada
pasa a **«Diferida (trabajo futuro)»** en `docs/tasks.md`, con lo que falta escrito en su fila (pregunta pendiente,
proveedor y fecha de envío), y se incorpora al capítulo «Limitaciones y trabajo futuro» de la memoria (DOC-14). Una
respuesta que llegue después del corte no reabre la tarea dentro de la entrega: se anota como insumo para el trabajo
futuro.
