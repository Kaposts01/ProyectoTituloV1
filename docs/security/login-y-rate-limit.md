# Login seguro y rate limit de la API (CRM-16A / CRM-16D)

Estado: implementado en la rama `feat/login-seguro` (local, sin desplegar). Requiere aplicar la migración
`20261114_0080` antes de desplegar el código (ver «Despliegue»).

## Punto de partida (antes de CRM-16A)

- `POST /api/v1/auth/login` con usuario y clave; JWT HS256 en cookie HttpOnly `SameSite=lax`, `Secure` salvo con
  `DEBUG=true`; CSRF por cabecera `X-CSRF-Token` comparada con el claim `csrf` del JWT; hash con `pwdlib`
  (`app/core/security.py`, `app/api/v1/routes/auth.py`).
- Sin límite de intentos ni bloqueo; un usuario inexistente respondía más rápido (no se calculaba hash).
- Cambio de clave propio con mínimo 6 caracteres y sin otras reglas (el panel de administración ya pedía 12).
- El logout solo borraba la cookie: el token seguía valiendo hasta expirar.
- Sin registro de accesos ni fallos. No existe endpoint de refresh.

## CRM-16A: login endurecido

### Límite de intentos con bloqueo progresivo

`app/core/rate_limit.py` (`LoginThrottle`, en memoria):

- Se cuentan los fallos por **usuario** (referencia seudónima del nombre, exista o no la cuenta) y por **IP**
  dentro de una ventana (`AUTH_LOGIN_FAILURE_WINDOW_SECONDS`, 900 s).
- Al llegar al umbral (`AUTH_LOGIN_MAX_FAILURES_PER_USER` = 5, `AUTH_LOGIN_MAX_FAILURES_PER_IP` = 20) la clave queda
  bloqueada `AUTH_LOGIN_LOCKOUT_BASE_SECONDS` (60 s); cada bloqueo siguiente dura el doble, con tope
  `AUTH_LOGIN_LOCKOUT_MAX_SECONDS` (3600 s). El escalamiento se reinicia tras un período largo sin fallos.
- Durante el bloqueo el login responde **429** con `Retry-After` y un mensaje genérico en español, incluso con la
  clave correcta. Un login exitoso limpia el contador del usuario (no el de la IP).
- Equivocar la clave actual en «Mi perfil» cuenta como fallo del usuario.
- Limitación: el estado es por proceso y se pierde al reiniciar (igual que el rate limit de webhooks). Con varios
  workers el límite efectivo se multiplica. Se eligió memoria para no crear una tabla nueva solo para contadores.

### Respuesta genérica

Usuario inexistente, inactivo o clave equivocada devuelven el mismo 401 `Invalid username or password`. Para los dos
primeros se verifica la clave contra un hash ficticio (`burn_password_check`) para que el tiempo de respuesta no
delate si la cuenta existe. El bloqueo también aplica a nombres inexistentes, así que tampoco lo delata.

### Política de claves nuevas

`app/core/password_policy.py`, aplicada al crear usuario, resetear clave (admin) y cambiar la propia clave:
largo mínimo `AUTH_PASSWORD_MIN_LENGTH` (12, nunca menos de 8), fuera de una lista embebida de claves comunes,
no uno o dos caracteres repetidos, no contener el nombre de usuario. **Las claves actuales no se revalidan**: el
cambio forzado de claves existentes queda para decisión del usuario (ficha).

### Sesión: expiración, rotación y logout

- El JWT lleva `sub`, `csrf`, `iat`, `exp` (`AUTH_ACCESS_TOKEN_MINUTES`, 60), `jti` y `tv` (versión de sesión).
- Nueva columna `users.token_version` (migración `20261114_0080`). `get_current_user` rechaza un token cuyo `tv` no
  coincide. Los tokens emitidos antes de la migración no traen `tv` y cuentan como 0: nadie pierde la sesión al
  desplegar.
- **Logout** incrementa la versión: el token queda inválido en el servidor (y las demás sesiones del mismo usuario
  también se cierran).
- **Cambio de la propia clave**: incrementa la versión (cierra las otras sesiones) y entrega a la sesión actual una
  cookie nueva y un `csrf_token` nuevo en la respuesta de `PATCH /api/v1/auth/me` (el frontend lo adopta).
- **Reseteo por un admin**: incrementa la versión del usuario reseteado (sus sesiones abiertas se cierran).
- No hay endpoint de refresh, así que no hay rotación de refresh token; la sesión expira a los 60 min.

### Registro de accesos y fallos

Logger `crm.auth.audit` (`app/core/auth_audit.py`). Eventos: `login_success`, `login_failed` (con
`detail=bad_password|unknown_or_inactive`), `login_lockout`, `login_blocked`, `logout`, `password_changed`,
`password_change_failed`. Cada línea lleva el `user_id` interno o `user_ref` (HMAC-SHA256 truncado del nombre con
la llave del JWT) y la IP truncada (/24 en IPv4, /48 en IPv6). Nunca el nombre, la clave ni el token.

### Cookie y CSRF

- `Secure` siempre en producción (aunque `DEBUG=true`); fuera de producción solo sin `DEBUG`.
- `SameSite` configurable con `AUTH_COOKIE_SAMESITE` (`lax` por defecto, `strict` admitido). Se mantiene `lax`:
  el CSRF ya lo cubre la cabecera `X-CSRF-Token`, y `strict` no aporta en una SPA del mismo origen.
- La comparación del token CSRF pasa a tiempo constante (`hmac.compare_digest`). El borrado de la cookie en el logout
  usa los mismos atributos con los que se creó.

## CRM-16D: rate limit de la API

`app/core/api_rate_limit.py`, middleware ASGI propio (sin dependencias nuevas), ventana fija de 60 s en memoria:

| Tráfico | Clave | Variable | Por defecto |
|---|---|---|---|
| `/api/...` general | IP | `API_RATE_LIMIT_IP_PER_MINUTE` | 1200 |
| `/api/...` con sesión válida | usuario (`sub` del JWT) | `API_RATE_LIMIT_USER_PER_MINUTE` | 600 |
| `/api/v1/webhooks/...` | IP de origen (todas las rutas juntas) | `API_RATE_LIMIT_WEBHOOK_IP_PER_MINUTE` | 300 |

- Exentos: lo que no empieza con `/api/` (frontend) y los prefijos de `API_RATE_LIMIT_EXEMPT_PATHS`
  (`/health,/api/v1/health`). `API_RATE_LIMIT_ENABLED=false` lo apaga; un límite en 0 apaga ese eje.
- Al superar: **429**, `Retry-After` en segundos y `detail` `{code: "rate_limited", message}`.
- Los webhooks conservan además su límite por (ruta, IP) de `WEBHOOK_RATE_LIMIT_PER_MINUTE` (RT-08).
- IP del cliente: `X-Forwarded-For` solo con `API_TRUSTED_PROXY_COUNT=N` (N = número de proxies o túneles propios delante del backend, como `TRUSTED_PROXY_COUNT` en Flota); se toma la IP en la posición N desde la derecha, así un cliente no puede falsificarla anteponiendo otra. Con 0 (por defecto) se ignora el header. Sin
  eso, detrás de un túnel todos los visitantes comparten una IP: con los valores por defecto (holgados) no debería
  molestar, pero el bloqueo por IP del login sí podría afectar a todos tras 20 fallos.

## Configuración nueva

`AUTH_LOGIN_MAX_FAILURES_PER_USER`, `AUTH_LOGIN_MAX_FAILURES_PER_IP`, `AUTH_LOGIN_FAILURE_WINDOW_SECONDS`,
`AUTH_LOGIN_LOCKOUT_BASE_SECONDS`, `AUTH_LOGIN_LOCKOUT_MAX_SECONDS`, `AUTH_PASSWORD_MIN_LENGTH`,
`AUTH_COOKIE_SAMESITE`, `API_TRUSTED_PROXY_COUNT`, `API_RATE_LIMIT_ENABLED`, `API_RATE_LIMIT_IP_PER_MINUTE`,
`API_RATE_LIMIT_USER_PER_MINUTE`, `API_RATE_LIMIT_WEBHOOK_IP_PER_MINUTE`, `API_RATE_LIMIT_EXEMPT_PATHS`.
Todas tienen valor por defecto; no hace falta tocar el `.env`.

## Despliegue

1. Aplicar `alembic upgrade head` (agrega `users.token_version` con default 0; sin backfill). Probada solo en la
   base de tests. Sin la columna, el código nuevo falla al leer usuarios: migrar antes de desplegar.
2. Desplegar el código. Las sesiones abiertas siguen valiendo hasta su expiración.

## Tests

`tests/test_auth_limits_unit.py` (piezas puras), `tests/test_login_hardening.py` (login, bloqueo, revocación,
política, registro, cookie) y `tests/test_api_rate_limit.py` (middleware). `tests/conftest.py` limpia los contadores
en memoria antes y después de cada test.

## AUTH-04: entrar con Google y correcciones de la QA (19/11/2026)

### Bloqueo por intentos del callback de Google (M1)

- Los fallos del callback previos a una transacción válida (`no_tx_cookie`, `bad_tx_cookie`, `state_mismatch`,
  `google_returned_error`) **no cuentan** en el bloqueo: solo van a la bitácora. Si no, un GET anónimo repetido
  bloquearía el login de toda la IP compartida (el proxy de Vite no reenvía `X-Forwarded-For`).
- Los fallos que sí cuentan (intercambio del código, `id_token`, usuario desconocido o inactivo) usan la clave propia
  `("google_ip", ip)`, separada de la `("ip", ip)` de `POST /login`. Google nunca bloquea el login con contraseña.

### Cookie temporal `oauth_tx` y SameSite (I1)

La cookie temporal usa `AUTH_COOKIE_SAMESITE` (`lax` por defecto). Con `strict` el navegador no la envía en el
retorno desde `accounts.google.com` (navegación entre sitios) y el login con Google falla siempre (falla cerrado).
Para AUTH-04 se requiere `lax`.

### Un solo worker (B2)

El bloqueo por intentos vive en memoria por proceso. El 8000 debe correr con **un solo worker**; con varios, cada
uno cuenta aparte y el límite efectivo se multiplica por N. Si eso cambia, hará falta un contador compartido.

### `code` y `state` en los logs de acceso (B5)

`code` y `state` viajan en la query de `GET /api/v1/auth/google/callback` y quedan en los logs de acceso de uvicorn
y Vite. El riesgo es bajo (de un solo uso, no canjeable sin el verifier de la cookie HttpOnly), pero si se conservan
o comparten logs de acceso, hay que filtrar la query de esa ruta.

### Administración de usuarios (SEC-04)

- `PUT /admin/users/{id}`: solo un usuario con rol `admin` puede asignar el rol `admin` (misma guarda que la
  creación, SEC-4).
- Las guardas SEC-1 y SEC-2 (modificar o resetear la contraseña de un admin) consideran admin a cualquier usuario con
  el rol `admin`, esté activo o no; un no-admin con `users.manage` no puede reactivar una cuenta admin inactiva, ni
  asignarle correo de Google, contraseña o roles. SEC-3 (último admin activo) no cambia.

### Tipo de sesión `typ` (B1)

El JWT de sesión lleva `"typ": "session"` y todas las decodificaciones de sesión (`get_current_user`,
`get_csrf_token`, el límite de la API y `session_guard`) lo exigen: un token sin `typ` o con otro (por ejemplo la
cookie temporal `oauth_tx`) se rechaza como sesión inválida. **Al desplegar, todas las sesiones abiertas dejan de
valer y todos vuelven a iniciar sesión** (aceptado en la decisión d257). Va en el mismo despliegue que AUTH-04.
