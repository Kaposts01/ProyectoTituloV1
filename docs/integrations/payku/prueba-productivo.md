# Prueba controlada en Payku PRODUCTIVO (CRM-14C)

Estado: **plan y dry-run**. Nada de esto se ejecutó contra Payku. Ejecutarlo requiere la aprobación del usuario por la
Bandeja (escritura en productivo con dinero real).

Contexto: Payku no tiene un sandbox usable para este proyecto; sí hay productivo con llaves. Para responder preguntas
abiertas de la integración se propone **una** suscripción de prueba, de monto mínimo, a nombre del propio usuario
(su correo y su RUT), sin pedir reembolso. Meta de costo: **≤ 51 CLP**.

Fuente: documentación oficial (<https://docs.payku.com/cl/>, copia local `payku-docs-es.md`). Lo que la doc no dice
se marca como **no documentado**; no se completa con suposiciones.

---

## 1. Qué dice la doc oficial

| Tema | Lo que dice | Cita |
|---|---|---|
| Monto mínimo de plan o suscripción en CLP | **No está documentado.** El único mínimo publicado es para Perú: "el monto mínimo es de 5 soles (PEN)". `amount` de la suscripción: "máximo 14 dígitos", moneda CLP. | Crear suscripción (campo `amount`); Perú › Payout (L8623) |
| Cargo inicial | "al realizar esta solicitud por primera vez se realizará un cobro de **$50** que permite comprobar que la tarjeta se encuentra activa y es válida". No dice si se devuelve (Q-15). | Crear suscripción, `POST /api/sususcription` (L4102) |
| Primer cobro | Plan fijo: "el cobro del servicio será automático a partir del mes siguiente de la fecha de suscripción". Plan de **monto variable**: no lo dice (Q-27). Plan de consumo: hay que usar `api/sutransaction`. | Crear suscripción (L4102) |
| Crear cliente | `POST /api/suclient`: `email` ✓ (≤50), `name` ✓ (≤80), `phone` ✓, `rut` opcional. | Crear cliente |
| Crear plan | `POST /api/suplan` solo aparece en *Suscripción de consumo*; body: `name` ✓ (≤20), `description`, `url_notify_suscription`, `url_notify_payment`, `url_success_payment`, `url_failed_payment`. **Sin monto ni tipo**: un plan de monto variable o fijo se configura en el panel (inferencia ya registrada en [plans.md](resources/plans.md)). | Suscripción de consumo › Crear plan |
| Crear suscripción | `POST /api/sususcription` `{plan, client, amount?}` → `{"status": "register", "id": "su…", "url": "…/gateway/registrosuscripcion?…"}`. La `url` es la de "pago y activación de suscripción". | Crear suscripción |
| Inscripción de tarjeta | El titular abre la `url` de la respuesta y registra su tarjeta (ahí se cobra la validación de $50). Para renovar tarjeta: `POST /api/suinscriptionscards {suscription}` devuelve una `url` nueva. | Crear suscripción; Afiliar tarjeta |
| Cancelar | `DELETE /api/sususcription/{id}` → `{"id": "su…", "status": "success"}`. Estado final (`delete` o `cancel`) no documentado (Q-13). | Eliminar suscripción |
| Notificaciones | `url_notify_suscription` (del plan): `{id, status}` con estados `register, active, finish, delete, cancel, suspended`. `url_notify_payment`: `{transaction_id, verification_key, order, status, subscriptions{id, client}}`. Solo llegan si el plan tiene esas URL. | url Callback notificación suscripción / cobro |
| Buscar previas | `GET /api/suclient/{id o email}` (detalle con sus suscripciones; id "máximo 20 caracteres", Q-10); `GET /api/suclient/customers` (≤100 por página; sin fecha toma la actual, Q-12); `GET /api/sususcriptionv3` (≤4000 por página, `date_init`/`date_end`). **No hay búsqueda por RUT**: se filtra en local. | Obtener cliente / clientes / suscripciones V3 |

## 2. Costo estimado

| Concepto | Monto | Cuándo |
|---|---|---|
| Validación de tarjeta | 50 CLP | Al inscribir la tarjeta (doc) |
| Monto de la suscripción | 1 CLP (`--amount 1`) | Al activar o el mes siguiente: es justo lo que mide Q-27 |
| **Total** | **51 CLP** | Si se cancela antes del siguiente ciclo |

Riesgos de costo: (a) si Payku rechaza `amount=1` por un mínimo no publicado, el script se detiene con el error de
Payku (no reintenta con más); subir el monto requiere decisión del usuario y `--max-total`. (b) Si no se cancela, se
cobra 1 CLP por ciclo. (c) La comisión de Payku sobre estos cobros no está en la doc de la API.

## 3. Paso a paso

Requisitos previos (usuario, en el panel de Payku): crear un **plan de monto variable** de prueba (nombre con
`CRM TEST`) y anotar su id `pl…`. Sin `--plan-id` el script crea el plan por API, pero su tipo no está documentado.

1. **Dry-run** (sin red, sin base; es lo único que se ha corrido):
   ```powershell
   .venv\Scripts\python.exe -m scripts.maintenance.payku_test_subscription --email <correo> --rut <RUT> `
     --phone <telefono> --name "<nombre>" --plan-id <pl_variable>
   ```
2. **Excluir de los indicadores** (§ 5): cargar el id `su…` en cuanto el alta lo imprima, antes del siguiente sync.
3. **Buscar suscripciones previas** (solo GET contra productivo; requiere confirmación del usuario):
   `--find-existing --execute-read --confirm-production`. El alta también lo hace y se niega si ya hay una suscripción
   `active` o `register` para ese correo o RUT; si el cliente ya existe, lo reutiliza.
4. **Alta** (escrituras; requiere aprobación): `--apply --confirm-production` con la variable de **proceso**
   `PAYKU_TEST_SUBSCRIPTION_ARMED=1`, `APP_ENV` productivo, `PAYKU_BASE_URL` en `app.payku.cl` y
   `PAYKU_WRITES_ENABLED=true` solo para ese proceso. Llama, en orden: `POST /api/suclient` (si no existía),
   `POST /api/suplan` (solo sin `--plan-id`), `POST /api/sususcription {plan, client, amount: "1"}`. Cada escritura queda
   en `write_runs` (`source=payku`, `operation=test_subscription.*`, correo/RUT enmascarados, marca `CRM-14C`).
5. **Inscribir la tarjeta**: el titular abre la `url` devuelta (cobro de 50 CLP).
6. **Lecturas de verificación** el mismo día y al día siguiente: `--verify <su…> --execute-read --confirm-production`
   (`GET /api/sususcription/{id}`, V3 del día, `GET /api/transaction` del día).
7. **Cancelar**: `--cancel <su…> --apply --confirm-production` (mismas llaves) → `DELETE /api/sususcription/{id}` y
   relectura del estado. Hacerlo antes del siguiente ciclo. Alternativa manual: el panel de Payku.

## 4. Qué preguntas responde (fichas d174–d181)

| Pregunta | ¿La responde? | Cómo |
|---|---|---|
| Q-01 firma sin parámetros | **Sí** | `GET /api/suclient/{email}`, `GET /api/sususcription/{id}` y el `DELETE` sin body se firman sin `&` final (`build_sign`); 200 vs 401 lo confirma también para escrituras |
| Q-02 `Sign` extra | **Parcial** | `GET /api/transaction` se envía con `Sign` (el cliente lo pone siempre); si responde 200, Payku tolera el header extra en ese endpoint |
| Q-06 cobros de suscripción en `/api/transaction` y conciliación | **Parcial** | Se buscan el cargo de $50 y el de 1 CLP en `GET /api/transaction` del día; conciliación (`POST /api/conciliation`) queda fuera del script |
| Q-08 clave estable del cobro | **Parcial** | Se ve `paid[]`/`transactions[]` de un cobro real; repeticiones de `paid_number`/`try_number` requieren varios ciclos |
| Q-11 `date_init`/`date_end` de V3 | **Sí** | La sub creada hoy debe aparecer en la ventana de hoy y no en una que la excluya |
| Q-27 cobro del plan variable al activar | **Sí** (objetivo principal) | Revisar `transactions[]` y V3 `paid[]` el día de la activación |
| Q-29 `url` nueva en `register` | **No por defecto** | Exige `POST /api/suinscriptionscards` antes de inscribir la tarjeta; no está en el script (se puede agregar si el usuario lo aprueba) |
| Q-33 M1 en conciliación | **No** | La prueba no hace un `POST /api/transaction` de primer aporte |

También aporta a Q-13 (estado tras `DELETE`) y Q-15 (si el cargo de $50 se ve como transacción).

## 5. Excluir la suscripción de prueba de los indicadores (d207, implementado)

Variable `PAYKU_KPI_EXCLUDED_IDS` (`app/core/config.py`, `.env.example`): lista de ids externos de **suscripción**
Payku (`su…`) separados por coma, vacía por defecto. Sus cobros, ciclos y pagos quedan fuera por su suscripción (no
hace falta cargar el número de transacción). Qué la respeta (`app/services/payku_kpi_exclusion.py`):

| Punto | Efecto |
|---|---|
| `channel_consolidation._consolidate_payku_subscriptions` / `_transactions` | No pasa la sub ni sus transacciones a `subscriptions`/`payments` (`source=payku`), que leen el tablero de Payku, el general, el churn y los rechazos |
| `core_payku_etl` | No materializa la sub, sus ciclos (`core_charges`) ni sus pagos (`core_payments`); al inicio retira de Core lo que ya existiera de esas subs (Core es derivado: sacar el id de la lista lo repone en la siguiente corrida) |
| `dashboard_general._mrr_by_channel` | MRR/ARPU de Payku sin la sub |
| `staging._payku_centralized_dashboard` (resumen de Payku) y conteo por plan | Última transacción `success` sin la sub |
| `recovery_payku` (recuperador: canceladas, suspendidas, rechazos) | Filtra la sub |
| `export_queries._charges_payku_cycles` (cobros generales y su export) | Filtra los ciclos de la sub |

Las tablas crudas `p_*` se conservan (trazabilidad); `p_clients`/`clients` no se filtran (el conteo de clientes de
Payku puede sumar uno).

**Cómo cargar el id antes del alta.** El id `su…` solo se conoce al crear la suscripción, así que el orden es:

1. Correr el alta (`--consumption --create-plan --apply …`). El script imprime `subscription_id`, la línea
   `PAYKU_KPI_EXCLUDED_IDS=su…` y un recordatorio.
2. **De inmediato**, antes del siguiente sync y antes de `--charge`, agregar ese id a `PAYKU_KPI_EXCLUDED_IDS` en el
   `.env` del CRM (sumándolo a la lista vigente, separado por coma) y reiniciar el backend/worker para que lo lea.
3. `--charge SUB_ID` (y su dry-run) avisa con `AVISO: … NO esta en PAYKU_KPI_EXCLUDED_IDS` si el id no está en la
   configuración que ve el proceso; no bloquea, así que si aparece el aviso hay que detenerse y cargarlo primero.

Si un sync alcanzó a consolidar la sub antes de cargar el id: Core se corrige solo en la siguiente corrida del ETL,
y las lecturas directas de arriba la filtran, pero las filas de `subscriptions`/`payments` ya consolidadas no se
borran solas (la consolidación solo deja de reescribirlas). Retirarlas es un borrado y va por la Bandeja.

Ojo con la identidad (ADR-001): un cliente Payku con el correo y el RUT del usuario puede emparejarse con un socio
existente del CRM.

## 6. Riesgos

- Dinero real: 50 CLP + 1 CLP por ciclo hasta cancelar. No se pide reembolso.
- Mínimo no documentado: Payku o Webpay pueden rechazar 1 CLP.
- `PAYKU_WRITES_ENABLED=true` habilita también las escrituras del CRM en ese proceso; usarlo solo en el proceso del
  script, nunca en el `.env` del servidor.
- El `write_run` usa la base de la app del ambiente activo (productivo), con correo y RUT enmascarados.
- La `url` de inscripción tiene vigencia no documentada (Q-16).
- Si la búsqueda previa falla por el límite de 20 caracteres del path (Q-10), el script recorre el listado de clientes.

## 7. Variante con plan de CONSUMO (ficha d213 = b)

El usuario aceptó que el plan quede **permanente** en la cuenta (solo se cancela la suscripción). Flujo, todo en
dry-run salvo `--apply` (mismas llaves de la sección 3: `--confirm-production`, `PAYKU_TEST_SUBSCRIPTION_ARMED=1` de
proceso, APP_ENV productivo con host `app.payku.cl` y `PAYKU_WRITES_ENABLED`), cada escritura en `write_runs`:

1. `--consumption --create-plan --email <correo> --rut <RUT> --phone <tel> --name <nombre>`: busca previas, crea
   cliente (o lo reutiliza), `POST /api/suplan` (`name` = `PRUEBA-CRM-1CLP`, sin `url_notify_*`), relee el plan y
   crea la suscripción **sin** `amount`. Imprime la url de inscripción, el id `su…` y la línea
   `PAYKU_KPI_EXCLUDED_IDS=su…` a cargar de inmediato (§ 5).
   El RUT y el correo solo van por argumento; nunca se escriben en archivos y salen enmascarados.
2. Paso **manual**: el titular abre la url e inscribe la tarjeta (cargo de validación de $50 según la doc).
3. `--charge SUB_ID`: relee la sub (se niega si no está `active`) y hace `POST /api/sutransaction` con
   `suscription`, `amount` = 1, `order` = `CRM14C-CONSUMO-AAMMDD` y `description`. Imprime `transaction_id` y la
   línea de exclusión a sumar.
4. `--verify-consumption SUB_ID --transaction-id N [--conciliation-date AAAA-MM-DD] --execute-read
   --confirm-production`: Q-06 (aparece en `GET /api/transaction` y en la conciliación, que es un POST de consulta),
   Q-08 (qué campo coincide con el `transaction_id`) y Q-33 (si la descripción lo distingue de un cobro recurrente).
5. `--cancel SUB_ID --apply ...`: baja de la suscripción. El plan no se borra.

Costo (texto del dry-run de `--consumption`):

- **Al activar** (inscribir la tarjeta): **0 CLP esperado**. Según el historial, Payku cobra al activar el monto
  completo de la suscripción; esta se crea sin `amount` y el plan de consumo no tiene monto, así que no hay monto que
  cobrar.
- **Cobro de consumo** (`--charge`): 1 CLP. **Total esperado: 1 CLP.**
- **Caso dudoso**: la doc (Crear suscripción, L4102) anuncia una validación de $50 al inscribir la tarjeta que **no
  aparece** en los datos de transacciones del CRM; también podría haber un cobro inicial de 0 o 1 CLP. Rango
  probable 1–2 CLP; peor caso 51 CLP (validación + cobro), dentro del tope `--max-total` 51. La lectura
  `--verify-consumption` del mismo día lo resuelve (`q15_cargo_50_en_listado`).

Un plan de consumo no cobra solo, así que no hay ciclos posteriores. Exclusión de indicadores: sección 5 (cargar el
id `su…` que imprime el alta antes del siguiente sync y de `--charge`).
