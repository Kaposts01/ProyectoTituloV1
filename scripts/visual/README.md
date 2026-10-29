# Capturas visuales del sandbox

Capturas de pantalla (solo lectura) del frontend sandbox `http://localhost:5174` con Playwright.

Playwright es de **Node** y **no es dependencia del proyecto**. En esta máquina está instalado fuera del repo
(`<scratchpad>\pw\node_modules\playwright`, v1.64.1); el script lo resuelve con `PLAYWRIGHT_NODE_DIR`
(carpeta que contiene `node_modules/playwright`, por defecto la `pw` del scratchpad). El Chromium de Playwright en caché
(`chromium-1234`) no coincide con esa versión, así que el script cae a **Google Chrome instalado** (`channel: "chrome"`).

## Uso

Requisitos previos: backend sandbox en `:8001` y frontend sandbox en `:5174` levantados (el script no los inicia).
Los datos `DEMO-` se siembran antes con `.venv\Scripts\python.exe scripts\sandbox\seed_billing_demo.py`.

```powershell
node scripts\visual\capture_sandbox.mjs --help
node scripts\visual\capture_sandbox.mjs --list

# 1) El USUARIO inicia sesión en la ventana visible (espera hasta 10 min); guarda el estado fuera del repo.
node scripts\visual\capture_sandbox.mjs login

# 2) Capturas headless: 2 viewports (1440x900, 390x844) x 2 temas (claro/oscuro) por pantalla.
node scripts\visual\capture_sandbox.mjs capture
node scripts\visual\capture_sandbox.mjs capture --only cambios-pendientes,dialogo-aprobar --viewports desktop --themes dark
```

Salida: `<scratchpad>\visual\<timestamp>\<pantalla>__<viewport>__<tema>.png` y `index.json` (estado por captura, errores
de consola/`pageerror`, respuestas HTTP >= 400 y peticiones bloqueadas; sin cuerpos ni cookies). El estado de sesión
(`<scratchpad>\visual\state.json`) contiene la cookie: nunca se imprime ni debe copiarse al repo.

## Guardas

- Solo `http://localhost:5174`; cualquier otra `--base-url` se rechaza.
- Se abortan peticiones a otros puertos de localhost (5173/8000 = producción local) y a hosts externos (solo se dejan pasar
  fuentes, estilos e imágenes por GET).
- Se abortan **todas** las peticiones de escritura (POST/PUT/PATCH/DELETE); los diálogos se abren pero nunca se confirman.
  Única excepción, solo en el modo `login` (la persona inicia sesión ella misma): `POST /api/v1/auth/login`. Sin esa
  excepción el login fallaba con «Failed to fetch» porque el propio script cancelaba la petición; `capture` no la tiene.
- Solo escribe dentro del scratchpad.
- Si el estado caducó o el backend sandbox se reinició (la sesión deja de valer), las capturas fallan con `SESION_INVALIDA`:
  volver a ejecutar `login`.
