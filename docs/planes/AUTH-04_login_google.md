# AUTH-04: entrar con Google (plan)

Pedido del usuario (2026-11-19): «Debemos agregar el oauth de google»; aclaración: solo cuentas @techo.org, con el cliente OAuth ya creado y sus variables `GOOGLE_OAUTH_*` en el `.env`. Decisiones: d249 = a (se mantiene el login con contraseña), d250 = a (alta previa: el administrador registra el correo @techo.org; nunca se crean usuarios). Planner en sonnet, solo lectura. Sin implementar. Pendientes: d253 (librería) y d254 (un cliente o dos).

## 1. URI de retorno para revisar en Google Cloud

| Ambiente | URI de retorno autorizada |
| --- | --- |
| Producción | `http://127.0.0.1:5173/api/v1/auth/google/callback` |
| Sandbox | `http://127.0.0.1:5174/api/v1/auth/google/callback` |

- Va el host de la web (el proxy) y no el del backend: las cookies del intercambio y de la sesión quedan en ese host.
- Google acepta `http://` con loopback (`127.0.0.1` con puerto y ruta) en clientes «Aplicación web».
- Siempre entrar por `127.0.0.1`, nunca por `localhost`: la coincidencia es exacta y la cookie está ligada al host.
- La URI sale de configuración (`GOOGLE_OAUTH_REDIRECT_URI`, `SANDBOX_GOOGLE_OAUTH_REDIRECT_URI`), nunca del encabezado Host.

## 2. Flujo

1. El botón «Entrar con Google» es un enlace a `GET /api/v1/auth/google/start`.
2. El backend genera `state`, `nonce` y `code_verifier` (PKCE S256), los guarda en una cookie temporal `crm_oauth_tx` (JWT HS256 con el secreto del ambiente; HttpOnly, SameSite=Lax, path `/api/v1/auth/google`, 10 minutos, un solo uso) y redirige a Google con `scope=openid email`, `hd=techo.org` (solo ayuda de interfaz) y `prompt=select_account`.
3. `GET /api/v1/auth/google/callback`: compara `state` en tiempo constante, borra la cookie e intercambia el `code` con `httpx` (ya instalado) enviando `code_verifier`.
4. Verifica el `id_token` con las claves públicas de Google (RS256 fijo): `aud`, `iss`, `exp`/`iat`, `nonce`, `email_verified`, `hd` igual al dominio permitido y dominio del correo.
5. Busca el usuario por `google_email` en minúsculas; tiene que existir y estar activo.
6. Emite la misma sesión que `/login` (`create_access_token`, `set_session_cookie`, `log_auth_event`) y redirige a `/`. Nada en la URL.
7. Todo fallo redirige a `/?login_error=google`, sin detalle; el motivo va solo a la bitácora.

## 3. Cambios

- **Configuración** (`app/core/config.py`): `google_oauth_client_id`, `_client_secret`, `_allowed_domain` (techo.org por defecto), `_enabled`, `_redirect_uri` y sus `SANDBOX_*` aplicados en `_apply_sandbox`. Si está habilitado y falta un dato, no arranca o queda desactivado. Nombres sin valores en `.env.example`.
- **Modelo y migración**: `User.google_email` (String 255, nullable) con índice único sobre `lower(google_email)` donde no es nulo. Migración nueva sobre `20261118_0083` (la que se integre primero entre AUTH-04 y REP-02 toma la 0084).
- **Endpoints**: `start` y `callback` en `PUBLIC_API_PATHS` (`app/core/session_guard.py`) y en `tests/test_authz_route_matrix.py`; 404 si está deshabilitado. `GET /system/environment` agrega `google_login_enabled`.
- **Administración** (`admin.py`, `UsersSubPanel.tsx`): campo «Correo de Google (@techo.org)», validado (dominio, minúsculas, único → 409). Cambiarlo o quitarlo revoca las sesiones del usuario; se audita sin el correo.
- **Login** (`LoginScreen.tsx`): botón visible solo si `google_login_enabled`; mensaje genérico con `?login_error=google`. El login con contraseña no cambia.

## 4. Seguridad

Verificación completa del token (sin saltarse `hd` ni `email_verified`; `alg=none` y HS256 rechazados); cookie de intercambio de un solo uso; mismo `login_throttle` por IP que el login; usuarios no registrados e inactivos reciben el mismo resultado; usuarios desactivados no entran; sin altas automáticas; redirección solo a rutas propias fijas; auditoría `google_login_success` y `google_login_failed` con motivo y sin correo ni token; `client_secret` nunca en la bitácora; si las claves de Google no responden, falla cerrado.

## 5. Pruebas (sin Google real)

`tests/test_google_auth.py` con `httpx` simulado y una clave RSA generada en la prueba: camino feliz; `state` ausente, incorrecto o reutilizado; `nonce`, `aud`, `iss`, `exp` inválidos; `hd` ausente o distinto; `email_verified` falso; correo no registrado; usuario inactivo; firma ajena; `alg=none`; deshabilitado (404); sin correo en respuestas ni bitácora; revocación al cambiar el correo; Administración (409, dominio, permisos); migración. Frontend: `LoginScreen.test.tsx` y `UsersSubPanel.test.tsx`.

## 6. Orden de trabajo

1. Configuración, sandbox y `.env.example` (backend).
2. Modelo y migración con su prueba (backend).
3. Flujo OAuth, `session_guard` y pruebas (backend/api).
4. Administración (api y frontend).
5. Login (frontend).
6. Docs: seguridad, PROJECT_STATE, nota de decisión y el procedimiento de Google Cloud.

**Despliegue:** (1) dependencia de d253 en el `.venv`, con el usuario; (2) URI registradas en Google Cloud; (3) migración en `crm_sandbox` y prueba en 5174 con la bandera encendida; (4) migración en `crm` y reinicio del 8000; (5) rebuild del 5173; (6) el administrador registra los correos. Se puede desplegar con la bandera apagada.

## 7. Riesgos y preguntas abiertas

- Verificar la firma necesita `cryptography` (no está en el `.venv`; PyJWT 2.14 y httpx 0.28 sí): d253.
- Un cliente OAuth para los dos ambientes o uno por ambiente: d254.
- Si se pierde una cuenta @techo.org, entra quien la tenga: la baja del usuario o del correo revoca sesiones.
- Cuentas recicladas o con alias: mejora opcional, guardar `google_sub` en el primer ingreso de un usuario ya registrado.
- El límite de intentos es por proceso (no se comparte entre producción y sandbox).

## Estado tras la QA (2026-11-20)

- QA de seguridad con Fable (`QA_AUTH-04.md`): aprobado con observaciones. Corregidos en la rama: M1 (fallos sin transacción no cuentan; clave propia `google_ip`), SEC-04/X1 y B4 (d255) y el `typ` de sesión (d257). B3 (`google_sub`, d256) queda como tarea de seguimiento.
- Re-verificación con sonnet (`QA_AUTH-04b.md`): aprobado con observaciones menores, que quedan anotadas sin corregir:
  - O1: el contador `google_ip` no se limpia tras un ingreso correcto. Es coherente con el login con contraseña, que tampoco limpia su contador por IP.
  - O2: el literal `"session"` del `typ` está repetido en `app/core/session_guard.py` y `app/core/security.py`; conviene una constante compartida.
  - O3: formato.
- Pruebas del líder (entorno aparte con `cryptography` 47.0.0): pytest 3761 pasan, 23 omitidas; vitest 1490/1490 (una corrida previa dio 1489/1490 sin cambios de frontend: falla intermitente sin rastrear).
