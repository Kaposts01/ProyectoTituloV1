# Pantalla «Bajas» (MGT-15): estructura, permisos, estados y pruebas

> Estado: implementada en el frontend (Sprint 5, rama `sprint-5/sync-confiable`, 2026-10-29). Consume el API `/api/v1/cancellations` descrito en [`docs/designs/baja-cascada.md`](../designs/baja-cascada.md) §5. Reglas del usuario: todo lo que ve la persona va en español, incluidos los VALORES (estados, pasos, motivos, canales y códigos de error; ver [`i18n-frontend.md`](i18n-frontend.md)); todo lo que va en el código va en inglés.

## 1. Estructura

Todo vive en `frontend/src/features/cancellations/` (la ruta, el menú y los botones directos tocan unos pocos archivos fuera de ella).

| Archivo | Qué hace |
|---|---|
| `types.ts` | Tipos del API (solicitud, detalle, vista previa de la cascada, resultado por paso, respuesta de aplicar) y los tres permisos (`subscriptions.cancellation.request`, `.approve`, `.view`). |
| `cancellationsApi.ts` | Cliente HTTP: vista previa, crear, listar, ver, eventos, aprobar, rechazar, retirar, reabrir y aplicar (con `dry_run`). Las escrituras pasan por `shared/csrfRetry.ts`: ante un 403 sin código (CSRF vencido) se refresca el token y se reintenta UNA vez; un 403 con código (`not_approver`…) no se reintenta. |
| `cancellationsQuery.ts` | Pestañas y consulta de la bandeja. |
| `cancellationLabels.ts`, `cancellationOutcome.ts` | Textos y tonos desde el catálogo, acciones visibles por estado y permiso, y el aviso del resultado de aplicar. |
| `cancellationErrors.ts` | Convierte un error del API en un mensaje en español **por `detail.code`** (dominio `cancellationError` de `i18n/es.ts`). El `message` del servidor y cualquier valor del proveedor nunca se muestran; el paso y el código de paso solo se conservan si están en el catálogo y el id de la solicitud abierta solo si es un UUID. |
| `CancellationsInbox.tsx` | Pantalla: pestañas, filtros, tabla, paginación, detalle, botón «Solicitar baja». La carga se deriva de la clave de la consulta (sin `setState` síncrono en efectos, para no sumar advertencias de lint). |
| `CancellationDetailView.tsx`, `CascadeView.tsx` | Detalle, vista previa de la cascada, resultado por paso, simulación y línea de tiempo. |
| `RequestCancellationDialog.tsx`, `cancellationForm.ts`, `subscriptionSearch.ts` | «Solicitar baja»: validación, vista previa obligatoria y búsqueda de la suscripción reutilizando las listas existentes. |
| `CancellationActions.tsx` | Aprobar, rechazar, retirar, reabrir y aplicar (con simulación). |
| `directCancel.ts`, `DirectCancelNote.tsx` | Contexto y texto de los botones directos de baja (§4). |

Se reutilizan, sin copiarlos, el diálogo accesible, los avisos, la tabla apilable y los estilos de `features/billing/` (`ui.tsx`, `billing.css`); `cancellations.css` solo agrega la lista de pasos. `billingApi.ts` no se tocó.

Ruta: `/general/bajas` (`AppRoute` `cancellations`), con permiso `subscriptions.cancellation.view`; sin él, AppCore redirige a la primera vista disponible. Menú: ítem «Bajas» en el grupo Operación, solo con el permiso de lectura (solicitar o aprobar sin poder leer no lo muestra).

## 2. Permisos por rol (D12)

| Rol | Ve la pantalla | Solicita baja | Aprueba, rechaza, reabre y aplica | Retira | Botones directos de baja |
|---|---|---|---|---|---|
| `admin` | sí | sí | sí | cualquiera | sí (único rol) |
| `jefatura` | sí | sí | sí | las suyas | no |
| `ejecutivo`, `soporte`, `coordinador` | sí, solo lectura | no | no | no | no |

La pantalla decide con los PERMISOS (no con el nombre del rol); el nombre `admin` solo se usa para retirar solicitudes ajenas y para los botones directos, igual que el backend. El servidor decide siempre en último término (`not_approver`, `self_approval_not_allowed`, `invalid_request_state`…) y sus códigos se muestran en español.

## 3. Estados y pestañas

| Pestaña | Estados | Qué se puede hacer |
|---|---|---|
| Pendientes | `pending` «Pendiente de aprobación», `approved` «Aprobada» | Aprobar o rechazar (pendiente), retirar (pendiente), aplicar (aprobada) |
| En ejecución | `applying` «Aplicándose», `pending_external` «En trámite» (TCH), `requires_reconciliation` «Requiere conciliación», `failed` «Fallida» | Reabrir (fallida o con conciliación); la baja de TCH se cierra sola con el Excel |
| Historial | `completed` «Completada», `rejected`, `withdrawn`, `expired`, `not_executable` | Solo lectura |

`failed` va en «En ejecución» aunque no ocupe el cupo de solicitud abierta: es lo que pide seguimiento (reabrir).

Flujo de «Aplicar»: el diálogo exige **simular primero** (`dry_run`: no escribe nada y muestra pasos por hacer y ya hechos, bloqueos como `INVOICE_IN_PROGRESS` y facturas por anular); «Confirmar y aplicar» se habilita solo con una simulación sin bloqueos y, si la baja es irreversible, con la casilla marcada. Nunca se usa `window.confirm`. Los avisos de conciliación, de TCH «en trámite» y de pasos manuales (rotulados «Paso manual», con su instrucción) están en el detalle y en el aviso posterior a aplicar.

## 4. Botones directos de baja (D12-7)

Desde el backend (`DELETE /writes/{virtualpos|toku|payku}/subscriptions/{id}` y Toku `status = CANCELLED`) exigen el rol `admin`. En el frontend, quien NO es admin ya no ve «Cancelar Sub» (lista y ficha de suscripción de VirtualPOS), «Cancelar» (suscripciones de la ficha del cliente de VirtualPOS), «Eliminar» de una suscripción de Toku o Payku (lista, ficha y relacionados) ni la opción «Cancelada» del cambio de estado de Toku. En su lugar ve el texto «use «Solicitar baja» en Bajas» (con enlace si puede abrir la pantalla). No cambian: «+ Cargo», Editar, pausar o activar en Toku y «Eliminar» de clientes, facturas y métodos de pago. El contexto tiene valor por defecto seguro (sin admin) y AppCore lo provee desde la sesión.

## 5. Qué falta

- **Exportación de TCH para tesorería/banco**: la baja de TCH queda «en trámite» y el detalle avisa que la revocación del mandato se hace en el banco, pero no hay descarga con las fichas pendientes (sin PAN). Depende del backend (MGT-13) y de definir el responsable bancario y el plazo (decisión 5 abierta).
- **Eliminación de medios de pago**: sigue siendo un paso MANUAL registrado (VirtualPOS sin API; Toku pendiente de decisión; Payku sin validar Q-09; TCH mandato en el banco). La pantalla solo lo rotula y explica; no tiene botón para marcarlo como hecho (MGT-11).
- **Cambio de monto por canal** (Toku, Payku y TCH): sin pantalla ni API (MGT-12, MGT-13 y MGT-14). VirtualPOS conserva la Opción A en «Cambios de cobro».
- La búsqueda de TCH usa el listado consolidado de suscripciones (necesita `dashboard.view`) y filtra por plataforma en el navegador: con un texto muy corto puede no mostrar fichas de TCH si el listado se llena con otros canales. El identificador siempre se puede escribir a mano.
- La vista previa se calcula con la última sincronización local; el ejecutor relee el proveedor antes de actuar (así lo dice la pantalla).
- `DESIGN.md` (raíz) aún lista el grupo Operación sin «Bajas»: pendiente de actualizar por quien tenga a cargo ese documento.

## 6. Pruebas

Todo con `fetch` o `api` simulados y datos sintéticos; ninguna llamada a proveedores. Se corren desde `frontend/`:

```bash
npx vitest run src/features/cancellations src/test/cancellations.route.test.tsx src/test/directCancel.test.tsx src/navigation.menu.test.ts
npm test        # suite completa
npm run build   # tsc -b
npm run lint    # oxlint: 18 advertencias preexistentes, ninguna nueva
```

- `cancellations.api.test.ts`: catálogo, errores por código sin eco del proveedor, cliente HTTP y reintento de CSRF, reglas de acciones por permiso.
- `cancellations.inbox.test.tsx`, `cancellations.actions.test.tsx`, `cancellations.form.test.ts`, `cancellations.mobile.test.tsx`, `cancellations.nav.test.tsx`: pantalla de solo lectura, solicitar, aprobar, rechazar, retirar, reabrir, aplicar con simulación, móvil y menú.
- `test/cancellations.route.test.tsx` y `test/directCancel.test.tsx`: integración con AppCore (permiso y redirección; botones directos solo para admin).

### Cómo probarla en sandbox

Sigue el runbook [`docs/operations/sandbox-testing-and-decisions.md`](../operations/sandbox-testing-and-decisions.md): primero las migraciones `20261029_0050` y `0051` y `seed_roles.py` en `crm_sandbox` (nunca en `crm` sin el usuario), y las llaves de sandbox. Luego `npm run dev:sandbox` en `frontend/` con el backend en `APP_ENV=sandbox`.

1. Con un usuario `jefatura`: «Solicitar baja» de una suscripción de prueba de VirtualPOS en sandbox; revisar la vista previa y enviar. Con la autoaprobación de la política queda «Aprobada».
2. Abrir el detalle y pulsar «Aplicar» → **Simular baja**: comprobar pasos, bloqueos y que no se escribió nada; luego confirmar. Verificar el resultado por paso y el paso manual del medio de pago.
3. Con `ejecutivo` o `soporte`: la pantalla se ve sin botones de acción.
4. Con un usuario no admin: en las listas y fichas de suscripción no hay botones directos de baja, solo el texto hacia «Solicitar baja».
5. Toku comparte host entre sandbox y producción: solo suscripciones `TEST-` en la lista permitida, y con el usuario. Payku está bloqueado en sandbox. TCH se prueba con el Excel sintético: la baja queda «En trámite» hasta cargar el siguiente.

## 7. Tanda L4-BAJAS (MGT-11 a MGT-15)

- `manualTasks.ts`, `ManualTasksPanel.tsx`, `ChangeAmountDialog.tsx`: pestaña «Tareas manuales» (con `subscriptions.manual_tasks.view`; confirmar/descartar/CSV con `.confirm`) y botón «Cambiar monto» (con `virtualpos.billing_changes.request`). Textos nuevos en `i18n/es.ts` (`manualTaskType`, `manualTaskStatus`, `manualTaskError` y entradas de `cancellationManual`), solo agregados.
- Pruebas: `cancellations.amount.test.tsx`. Los puntos «Exportación de TCH», «Eliminación de medios de pago» y «Cambio de monto por canal» del §5 quedan cubiertos (ver `docs/designs/baja-cascada.md` §6).
