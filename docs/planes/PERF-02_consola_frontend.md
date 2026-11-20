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
