# PERF-02: mensajes de consola del frontend y tiempo de carga (plan)

Pedido del usuario (2026-11-18): «Agreguemos a las tareas revisar los console log para mejorar la carga del front». Rama `perf/consola-frontend` desde `master` 3b63989.

## Lo que ya se midió (lectura del código, 2026-11-19)

- En `frontend/src` (173 archivos sin pruebas) solo hay **3 llamadas a `console`**:
  - `features/admin/AdminUsers.tsx:20` y `:24`: `console.error` cuando falla la carga de roles o permisos. Son errores reales, no depuración.
  - `i18n/label.ts:39`: `console.warn` de valores sin traducir, ya limitado a desarrollo (`import.meta.env.DEV`), una vez por valor y sin datos personales.
- **No hay `console.log` de depuración que quitar.** Lo que se vea en la consola del navegador viene de otro lado: avisos de React, de Vite, de librerías, errores de red o el propio aviso de i18n.
- **Hallazgo principal para la carga:** la web de producción (5173) corre con `npm run dev`, el servidor de desarrollo de Vite. Eso significa:
  - módulos sin empaquetar (cientos de pedidos al abrir la primera pantalla) y React en modo desarrollo, más lento;
  - `StrictMode` monta dos veces los efectos en desarrollo, así que cada pantalla puede hacer el doble de pedidos a la API;
  - los avisos solo de desarrollo (i18n, React) aparecen en producción.
  El backend ya sabe servir una build (`app/main.py:31`, `frontend/dist`); la `dist` de la carpeta principal es del 4/11 y está desactualizada.

## Plan

1. **Criterio de medición (antes de medir).** Pantallas: Dashboard, Cartera › Suscripciones y Detalle por canal › VirtualPOS. Por pantalla, carga en frío con caché vacía y en caliente; 3 repeticiones, mediana. Métricas: tiempo hasta el contenido principal visible (DOMContentLoaded y fin del último pedido a la API), número de pedidos y KB transferidos, y la lista de mensajes de consola (tipo y origen, sin valores). Siempre en sandbox (5174 o build sobre 8001), con el mismo navegador y sin otras pestañas.
2. **Lectura de la consola en sandbox.** Con un usuario temporal de solo lectura (como el de las capturas), abrir las tres pantallas y clasificar cada mensaje: error real, aviso de desarrollo, aviso de librería, pedido fallido. Sin copiar datos personales: solo tipo, archivo y texto genérico.
3. **Correcciones de código** según lo que salga en 2 (lo esperado es poco: claves de React, pedidos duplicados, valores sin traducir que faltan en i18n). Los dos `console.error` de `AdminUsers` se dejan, o pasan a un aviso visible si la pantalla queda vacía sin explicación.
4. **Medición comparada servidor de desarrollo vs. build** en sandbox: misma pauta del paso 1 contra 5174 (dev) y contra la build servida por un backend de sandbox. Es la medición que dice cuánto se ganaría.
5. **Propuesta de despliegue** (ficha aparte, crítica porque cambia cómo corre producción): servir la web de producción desde la build (`npm run build` + backend 8000, o `vite preview`) en lugar de `npm run dev`, con el paso de build agregado a la ventana de despliegue y a REANUDAR_SESIONES.md.

## Tamaño y cadena

- Pasos 1 a 3: chicos (frontend, una rama, QA liviana).
- Pasos 4 y 5: medianos por el cambio de operación de producción; van por la cadena normal y con ficha antes de tocar 5173.
- Trabajo pesado: el build y la suite de vitest se piden con turno del Orquestador.

## Restricciones

Sin datos personales en consola, capturas ni informe. Nada en producción sin ficha y confirmación en el chat. Modelo sonnet.

## Resultados de los pasos 1 a 3 (2026-11-19, sandbox 5174, servidor de desarrollo)

Criterio aplicado (escrito arriba, paso 1): Dashboard (`/central/resumen`), Cartera › Suscripciones (`/central/suscripciones`) y Detalle por canal › VirtualPOS (`/virtualpos/resumen`); usuario temporal de solo lectura en crm_sandbox, borrado al terminar; Chrome, una pestaña. Medido con `performance.getEntriesByType`. Una sola pasada por pantalla (no las 3 repeticiones del criterio: las cifras en caliente varían poco y la comparación de fondo queda para el paso 4).

### Consola

- En las tres pantallas, solo mensajes del propio servidor de desarrollo: `[vite] connecting/connected` y el aviso de React DevTools. **Ningún error, ningún aviso de React, ningún valor sin traducir, ningún pedido fallido.** Nada con datos personales.

### Pedidos y tiempos

| Pantalla | Módulos JS | Fin de módulos | Pedidos a la API | Fin del último pedido |
| --- | --- | --- | --- | --- |
| Dashboard, en caliente | 98 | 191 ms | 6 | 534 ms |
| Cartera › Suscripciones | 83 | 166 ms | 8 | 548 ms |
| VirtualPOS › Resumen | 99 | 309 ms | 5 | 264 ms |
| Primera carga tras el login (frío, después del `npm ci`) | 97 | — | 7 | **13,4 s**, 5,2 MB |

- `/auth/me` se pide dos veces en cada carga y los listados se piden, se cancelan y se repiten: es el doble montaje de `StrictMode`, que solo ocurre en el servidor de desarrollo. En una build no pasa.
- Hay ~300 ms entre la salud de canales y el pedido de datos de cada pantalla: es la carga perezosa de la vista (VirtualPOS baja ~20 módulos más, entre ellos `recharts`, después del primer render).
- La primera carga en frío (13,4 s y 5,2 MB) es la que el usuario nota: Vite transforma y sirve cada módulo por separado. Es el argumento para los pasos 4 y 5.

### Paso 3: correcciones

**No hay correcciones de código que valgan la pena.** No hay `console.log` de depuración; los dos `console.error` de `AdminUsers` son errores reales y se dejan; el aviso de i18n ya está limitado a desarrollo y no apareció. Los pedidos duplicados son del modo desarrollo. Se cierra el paso 3 sin cambios de código: no hay PR que pedir.

## Propuesta para los pasos 4 y 5 (solo texto; detenidos hasta que el Maestro lo decida con el usuario)

1. **Medir (PERF-02c), en sandbox:** misma pauta contra 5174 (desarrollo) y contra la build servida por un backend de sandbox en otro puerto (`npm run build` en el worktree y el backend sirviendo `frontend/dist`). Tres repeticiones en frío y en caliente por pantalla. Necesita un turno corto para la build.
2. **Desplegar (PERF-02d), con ficha crítica y confirmación en el chat:** que producción sirva la build. Dos caminos:
   - a) el backend 8000 sirve `frontend/dist` (ya lo hace si existe) y la web se abre en `127.0.0.1:8000`; 5173 queda solo para desarrollo. Agrega `npm run build` a cada despliegue y a REANUDAR_SESIONES.md.
   - b) `vite preview` en 5173 sobre la build, con el mismo proxy; mantiene la URL de hoy.
   Ninguno toca la base. Vuelta atrás: volver a `npm run dev`.

## Paso 4: medición servidor de desarrollo contra build (2026-11-19)

Aprobado por el usuario vía el Maestro («Sí, el paso 4»), con turno pesado del Orquestador. Sandbox: desarrollo en 5174 (backend 8001) contra build servida por un backend de sandbox propio en 8004 desde este worktree (`npx vite build --mode sandbox`); los dos contra `crm_sandbox`. Usuario temporal de solo lectura, borrado al terminar. Chrome, una pestaña. «Frío» = recarga sin caché (Ctrl+Shift+R) con el servidor ya encendido; «caliente» = navegación normal. «Listo» = fin del último pedido de la página (módulos y API). Mediana de 3 pasadas (2 en tres casos en caliente).

| Pantalla | Desarrollo frío | Build frío | Desarrollo caliente | Build caliente |
| --- | --- | --- | --- | --- |
| Dashboard | 629 ms · 4,8 MB · 105 pedidos | 223 ms · 0,5 MB · 15 | 572 ms | 198 ms |
| Cartera › Suscripciones | 340 ms · 4,8 MB · 92 | 147 ms · 0,5 MB · 18 | ~370 ms | ~115 ms |
| VirtualPOS › Resumen | 314 ms · 4,8 MB · 105 | 157 ms · 0,5 MB · 19 | ~270 ms | 146 ms |

- La build tarda entre la mitad y un tercio, baja ~10 veces menos datos (0,5 MB contra 4,8 MB) y hace ~6 veces menos pedidos.
- Con la build cada pedido a la API sale una sola vez (sin el doble montaje de StrictMode).
- **Lo que más nota el usuario es otra cosa:** la primera carga después de encender o reiniciar el servidor de desarrollo (o tras `npm ci`) tardó **13,4 s** (paso 2), porque Vite transforma todo al primer pedido. Con la build ese costo no existe: los archivos ya están listos.
- En esta máquina la red es local; en otra máquina de la red la diferencia de 4,8 MB contra 0,5 MB pesa más.
