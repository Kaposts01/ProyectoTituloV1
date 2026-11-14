"""CRM-16C: matriz de autorizacion por rol sobre TODAS las rutas de la API (`app.routes` de FastAPI).

Tres perfiles, con datos sinteticos y dentro de una transaccion que se revierte:
  - anonimo: sin cookie de sesion.
  - minimo: rol con una sola vista (`dashboard.view`).
  - otro alcance: rol con todos los permisos del canal Toku (y ninguno de VirtualPOS, Payku ni TCH).

Reglas que se verifican:
  1. Toda ruta que no sea una excepcion publica exige sesion: sin cookie responde 401, aunque el cuerpo sea JSON roto
     (el guardia `app/core/session_guard.py` corta antes de leer el cuerpo; antes salia 422).
  2. Con sesion pero sin el permiso, la ruta responde 403 ANTES de validar el cuerpo y los parametros: se envia un
     cuerpo vacio `{}` y parametros de ruta con tipo invalido; si la validacion fuera primero saldria 422.
  3. Ninguna ruta de escritura (POST/PUT/PATCH/DELETE) queda sin dependencia de permiso o rol, salvo las listadas
     abajo con su justificacion; y todas exigen CSRF salvo las brechas conocidas (`KNOWN_NO_CSRF`).
  4. Toda ruta nueva tiene que quedar clasificada: si aparece una ruta sin permiso declarado que no este en ninguna
     lista, el test falla.

Las rutas que el perfil SI puede usar no se invocan (podrian escribir en proveedores); solo se cuentan.
"""

from __future__ import annotations

import inspect
import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.v1.routes.crm import get_db as crm_get_db
from app.core.config import settings
from app.core.security import ACCESS_COOKIE, CSRF_HEADER, create_access_token, get_current_user, require_csrf
from app.core.security import get_db as security_get_db
from app.db.session import engine
from app.main import app
from app.models.auth import Permission, Role, User
from app.services import rbac

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# ── Excepciones publicas (sin sesion), con su justificacion ──────────────────────────────────────────────────────
PUBLIC: dict[tuple[str, str], str] = {
    ("POST", "/api/v1/auth/login"): "inicio de sesion",
    ("GET", "/api/v1/system/environment"): "la pantalla de login muestra el ambiente; sin datos personales",
    ("GET", "/api/v1/health/heartbeat"): "latido para el monitor externo (d139c); sin datos personales",
    ("GET", "/health"): "salud del proceso para el orquestador; sin datos",
    ("POST", "/api/v1/webhooks/toku"): "proveedor; firma HMAC Toku-Signature con ventana de 5 min",
    ("POST", "/api/v1/webhooks/payku/{kind}"): "proveedor; token secreto ?k= comparado en tiempo constante",
    ("POST", "/api/v1/webhooks/virtualpos/{kind}"): (
        "proveedor; payout con HMAC. payment/subscription/cargos sin firma documentada por VirtualPOS: solo se "
        "guardan ids y el procesador relee por API (hallazgo MEDIO documentado en docs/security/owasp-2026-11-14.md)"
    ),
}

# ── Solo sesion: recursos del propio usuario, sin permiso por diseno ──────────────────────────────────────────────
SESSION_ONLY: dict[tuple[str, str], str] = {
    ("GET", "/api/v1/auth/me"): "datos de la propia sesion",
    ("PATCH", "/api/v1/auth/me"): "perfil propio; exige la clave actual y CSRF",
    ("POST", "/api/v1/auth/logout"): "cierra la propia sesion; exige CSRF",
    ("GET", "/api/v1/export/jobs"): "lista SOLO las exportaciones del usuario (export_jobs.list_user_jobs)",
    ("GET", "/api/v1/export/jobs/{job_id}"): "solo jobs del usuario (export_jobs.user_job, 404 si es ajeno)",
    ("GET", "/api/v1/export/jobs/{job_id}/download"): "solo jobs del usuario (export_jobs.user_job, 404 si es ajeno)",
}

# ── Brechas conocidas (documentadas como pendientes, severidad BAJA/MEDIA) ───────────────────────────────────────
KNOWN_NO_PERMISSION: dict[tuple[str, str], str] = {
    ("GET", "/api/v1/scheduler/runs/{run_id}/stream"): "cualquier sesion sigue el progreso de un run; deberia exigir sync_runs.view",
}
KNOWN_NO_CSRF: dict[tuple[str, str], str] = {
    ("POST", "/api/v1/scheduler/jobs/{job_id}/run"): "SameSite=Lax mitiga; agregar require_csrf (ficha)",
    ("POST", "/api/v1/core/identity/match-candidates/{candidate_id}/review"): "SameSite=Lax mitiga; agregar require_csrf (ficha)",
}

# ── Permiso dentro del handler (depende del canal/fuente pedido) ─────────────────────────────────────────────────
# Se piden con parametros VALIDOS de VirtualPOS (fuera del alcance de ambos perfiles). `in_scope` = perfiles a los que
# la ruta SI da acceso con esos parametros (no se invocan). Aqui la validacion de query va antes del permiso: con
# parametros invalidos un usuario sin permiso ve 422 (hallazgo BAJO documentado).
@dataclass(frozen=True)
class Dyn:
    path_values: dict[str, str] = field(default_factory=dict)
    query: dict[str, str] = field(default_factory=dict)
    in_scope: frozenset[str] = frozenset()


_VP_SRC = {"source": "virtualpos1"}
_VP_CANAL = {"canal": "virtualpos"}
DYNAMIC: dict[tuple[str, str], Dyn] = {
    ("GET", "/api/v1/staging/records"): Dyn(query=_VP_SRC),
    ("GET", "/api/v1/staging/records/filter-values"): Dyn(
        query={"source": "virtualpos1", "resource_type": "client", "filter_field": "all"}),
    ("GET", "/api/v1/staging/virtualpos/clients/{external_id}"): Dyn(),
    ("GET", "/api/v1/staging/virtualpos/plans/{external_id}"): Dyn(),
    ("GET", "/api/v1/staging/virtualpos/subscriptions/{external_id}"): Dyn(),
    ("GET", "/api/v1/staging/virtualpos/charges/{external_id}"): Dyn(),
    ("GET", "/api/v1/staging/virtualpos/payments/{external_id}"): Dyn(),
    ("GET", "/api/v1/staging/{source}/{resource_type}/{external_id}"): Dyn(
        path_values={"source": "payku", "resource_type": "client"}),  # solo toku/payku
    ("GET", "/api/v1/staging/dashboard/{source}/alerts/{alert_id}"): Dyn(path_values=_VP_SRC),
    ("GET", "/api/v1/staging/dashboard/{source}"): Dyn(path_values=_VP_SRC),
    ("POST", "/api/v1/export/{entity}/jobs"): Dyn(path_values={"entity": "clientes"}, query=_VP_CANAL),
    ("GET", "/api/v1/export/{entity}/count"): Dyn(path_values={"entity": "clientes"}, query=_VP_CANAL),
    ("GET", "/api/v1/export/{entity}"): Dyn(path_values={"entity": "clientes"}, query=_VP_CANAL),
    ("GET", "/api/v1/reports/automatic"): Dyn(in_scope=frozenset({"minimo"})),  # dashboard.view
    ("GET", "/api/v1/reports/{scope}"): Dyn(
        path_values={"scope": "virtualpos"}, query={"date_from": "2026-01-01", "date_to": "2026-02-01"}),
    ("GET", "/api/v1/general/charges"): Dyn(query=_VP_CANAL),
    ("GET", "/api/v1/general/charges/statuses"): Dyn(query=_VP_CANAL),
    ("GET", "/api/v1/general/charges/summary"): Dyn(query=_VP_CANAL),
    ("GET", "/api/v1/general/payments"): Dyn(query=_VP_CANAL),
    ("GET", "/api/v1/general/payments/statuses"): Dyn(query=_VP_CANAL),
    ("GET", "/api/v1/general/subscriptions"): Dyn(query=_VP_CANAL),
    ("GET", "/api/v1/general/subscriptions/statuses"): Dyn(query=_VP_CANAL),
    ("GET", "/api/v1/imports/status"): Dyn(in_scope=frozenset({"otro"})),  # toku.reports.import
}


# ── Inventario de rutas y de sus dependencias de autorizacion ───────────────────────────────────────────────────
@dataclass
class RouteAuthz:
    method: str
    path: str
    has_body: bool
    session: bool = False
    csrf: bool = False
    all_of: list[frozenset[str]] = field(default_factory=list)
    any_of: list[frozenset[str]] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)

    @property
    def key(self) -> tuple[str, str]:
        return (self.method, self.path)

    @property
    def declares_permission(self) -> bool:
        return bool(self.all_of or self.any_of or self.roles)

    def allows(self, codes: set[str], role_names: set[str]) -> bool:
        return (
            all(req <= codes for req in self.all_of)
            and all(req & codes for req in self.any_of)
            and all(role in role_names for role in self.roles)
        )


def _iter_api_routes() -> Iterator[tuple[str, frozenset[str], object, bool]]:
    try:  # FastAPI >= 0.140: los routers incluidos quedan como _IncludedRouter; esto los aplana con su prefijo
        from fastapi.routing import iter_route_contexts
    except ImportError:  # pragma: no cover - FastAPI antiguo
        for route in app.routes:
            if isinstance(route, APIRoute):
                yield route.path, frozenset(route.methods), route.dependant, route.body_field is not None
        return
    for ctx in iter_route_contexts(app.routes):
        if isinstance(ctx.original_route, APIRoute):
            yield ctx.path, frozenset(ctx.methods), ctx.dependant, getattr(ctx, "body_field", None) is not None


def _collect(dependant, spec: RouteAuthz) -> None:
    for sub in dependant.dependencies:
        call = sub.call
        name = getattr(call, "__qualname__", "")
        if call is get_current_user:
            spec.session = True
        elif call is require_csrf:
            spec.csrf = True
        elif name.startswith(("require_permissions.", "require_any_permission.", "require_role.")):
            spec.session = True
            free = inspect.getclosurevars(call).nonlocals
            if name.startswith("require_permissions."):
                spec.all_of.append(frozenset(free["required"]))
            elif name.startswith("require_any_permission."):
                spec.any_of.append(frozenset(free["required"]))
            else:
                spec.roles.append(free["role_name"])
        _collect(sub, spec)


def _inventory() -> list[RouteAuthz]:
    out: list[RouteAuthz] = []
    for path, methods, dependant, has_body in _iter_api_routes():
        for method in sorted(methods - {"HEAD", "OPTIONS"}):
            spec = RouteAuthz(method=method, path=path, has_body=has_body)
            _collect(dependant, spec)
            out.append(spec)
    return out


ROUTES = _inventory()
PROTECTED = [r for r in ROUTES if r.key not in PUBLIC]


def _ids(routes: list[RouteAuthz]) -> list[str]:
    return [f"{r.method} {r.path}" for r in routes]


def _url(route: RouteAuthz, values: dict[str, str] | None = None) -> str:
    # Valor por defecto de tipo invalido a proposito (no es UUID ni entero): si la validacion de parametros fuera
    # antes que el permiso, la respuesta seria 422 y no 403.
    values = values or {}
    return re.sub(r"\{([^}:]+)(?::[^}]+)?\}", lambda m: values.get(m.group(1), "no-es-un-id"), route.path)


# ── 1-4: reglas estaticas sobre el inventario ────────────────────────────────────────────────────────────────────
def test_inventory_covers_the_whole_api() -> None:
    assert len(ROUTES) > 150, "el inventario no recorrio los routers incluidos"
    keys = {r.key for r in ROUTES}
    listed = set(PUBLIC) | set(SESSION_ONLY) | set(KNOWN_NO_PERMISSION) | set(KNOWN_NO_CSRF) | set(DYNAMIC)
    assert listed <= keys, f"excepciones que ya no existen (limpiar la lista): {sorted(listed - keys)}"


def test_every_non_public_route_requires_a_session() -> None:
    missing = [r.key for r in PROTECTED if not r.session]
    assert not missing, f"rutas sin get_current_user ni require_*: {missing}"


def test_every_route_without_declared_permission_is_classified() -> None:
    unclassified = [
        r.key for r in PROTECTED
        if not r.declares_permission and r.key not in SESSION_ONLY and r.key not in DYNAMIC and r.key not in KNOWN_NO_PERMISSION
    ]
    assert not unclassified, f"rutas sin permiso declarado ni justificacion: {unclassified}"


def test_no_write_route_without_permission_dependency() -> None:
    allowed = set(SESSION_ONLY) | {("POST", "/api/v1/export/{entity}/jobs")}  # export: permiso por canal en _resolve
    bad = [r.key for r in PROTECTED if r.method in WRITE_METHODS and not r.declares_permission and r.key not in allowed]
    assert not bad, f"rutas de escritura sin dependencia de permiso: {bad}"


def test_every_write_route_requires_csrf_except_known_gaps() -> None:
    no_csrf = {r.key for r in PROTECTED if r.method in WRITE_METHODS and not r.csrf}
    assert no_csrf == set(KNOWN_NO_CSRF), f"cambio en rutas de escritura sin CSRF: {sorted(no_csrf ^ set(KNOWN_NO_CSRF))}"


# ── Perfiles sinteticos ──────────────────────────────────────────────────────────────────────────────────────────
MINIMAL_CODES = {"dashboard.view"}


def _other_scope_codes() -> set[str]:
    return {code for code in rbac.PERMISSIONS if code.startswith("toku.") or ".toku." in code}


@dataclass
class Profile:
    name: str
    codes: set[str]
    role_names: set[str]
    client: TestClient
    csrf: str


@pytest.fixture(scope="module")
def profiles() -> Iterator[dict[str, Profile]]:
    mp = pytest.MonkeyPatch()
    mp.setattr(settings, "auth_jwt_secret", "test-jwt-secret-crm16c-with-at-least-32-chars")
    connection = engine.connect()
    transaction = connection.begin()
    db = Session(bind=connection, join_transaction_mode="create_savepoint")
    app.dependency_overrides[crm_get_db] = lambda: db
    app.dependency_overrides[security_get_db] = lambda: db
    try:
        rbac.seed_permissions(db)
        perms = {p.code: p for p in db.query(Permission)}
        out: dict[str, Profile] = {}
        for name, codes in (("minimo", MINIMAL_CODES), ("otro", _other_scope_codes())):
            codes = {c for c in codes if c in perms}
            role = Role(name=f"authz-{name}-{uuid.uuid4().hex[:8]}")
            role.permissions = [perms[c] for c in sorted(codes)]
            user = User(username=f"authz-{name}-{uuid.uuid4().hex[:8]}", password_hash="x", is_active=True, roles=[role])
            db.add_all([role, user])
            db.flush()
            token, csrf = create_access_token(user)
            client = TestClient(app, base_url="https://testserver", raise_server_exceptions=False)
            client.cookies.set(ACCESS_COOKIE, token)
            out[name] = Profile(name, codes, {role.name}, client, csrf)
        assert "toku.customers.update" in out["otro"].codes and not any(c.startswith("virtualpos.") for c in out["otro"].codes)
        yield out
    finally:
        app.dependency_overrides.pop(crm_get_db, None)
        app.dependency_overrides.pop(security_get_db, None)
        db.close()
        transaction.rollback()
        connection.close()
        mp.undo()


# ── 1: anonimo -> 401 antes de leer el cuerpo ────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("route", PROTECTED, ids=_ids(PROTECTED))
def test_anonymous_gets_401_even_with_broken_body(route: RouteAuthz, monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-crm16c-with-at-least-32-chars")
    client = TestClient(app, base_url="https://testserver", raise_server_exceptions=False)
    kwargs = {}
    if route.method in WRITE_METHODS:
        kwargs = {"content": b'{"roto": ', "headers": {"content-type": "application/json"}}
    response = client.request(route.method, _url(route), **kwargs)
    assert response.status_code == 401, f"{route.method} {route.path}: {response.status_code} {response.text[:200]}"


def test_anonymous_multipart_upload_is_rejected_before_parsing(monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-crm16c-with-at-least-32-chars")
    client = TestClient(app, base_url="https://testserver", raise_server_exceptions=False)
    response = client.post("/api/v1/imports/toku-reports", files={"report": ("x.xlsx", b"PK\x03\x04" + b"0" * 2048)})
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "authentication_required"


def test_forged_session_cookie_gets_401(monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-crm16c-with-at-least-32-chars")
    client = TestClient(app, base_url="https://testserver", raise_server_exceptions=False)
    client.cookies.set(ACCESS_COOKIE, "eyJhbGciOiJub25lIn0.eyJzdWIiOiIxIn0.")
    response = client.post("/api/v1/admin/users", content=b"{", headers={"content-type": "application/json"})
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_or_expired_session"


# ── 2: con sesion y sin permiso -> 403 antes de validar ──────────────────────────────────────────────────────────
DECLARED = [r for r in PROTECTED if r.declares_permission]
DYNAMIC_ROUTES = [r for r in PROTECTED if r.key in DYNAMIC]


def _request_as(profile: Profile, route: RouteAuthz, values: dict[str, str] | None = None, query: dict | None = None):
    kwargs: dict = {"headers": {CSRF_HEADER: profile.csrf}, "params": query or {}}
    if route.has_body:
        kwargs["json"] = {}  # cuerpo vacio: si el esquema se validara antes del permiso saldria 422
    return profile.client.request(route.method, _url(route, values), **kwargs)


@pytest.mark.parametrize("profile_name", ["minimo", "otro"])
@pytest.mark.parametrize("route", DECLARED, ids=_ids(DECLARED))
def test_declared_permission_is_checked_before_validation(route: RouteAuthz, profile_name: str, profiles) -> None:
    profile = profiles[profile_name]
    if route.allows(profile.codes, profile.role_names):
        pytest.skip("en alcance del perfil: no se invoca (podria escribir)")
    response = _request_as(profile, route)
    assert response.status_code == 403, f"{route.method} {route.path}: {response.status_code} {response.text[:200]}"


@pytest.mark.parametrize("profile_name", ["minimo", "otro"])
@pytest.mark.parametrize("route", DYNAMIC_ROUTES, ids=_ids(DYNAMIC_ROUTES))
def test_handler_permission_denies_out_of_scope(route: RouteAuthz, profile_name: str, profiles) -> None:
    dyn = DYNAMIC[route.key]
    if profile_name in dyn.in_scope:
        pytest.skip("en alcance del perfil: no se invoca")
    response = _request_as(profiles[profile_name], route, dyn.path_values, dyn.query)
    assert response.status_code == 403, f"{route.method} {route.path}: {response.status_code} {response.text[:200]}"


# ── Excepciones publicas: los webhooks firmados rechazan sin credencial ──────────────────────────────────────────
def test_signed_webhooks_reject_unsigned_requests(monkeypatch) -> None:
    monkeypatch.setattr(settings, "toku_webhook_secret", "whsec-sintetico-crm16c")
    monkeypatch.setattr(settings, "payku_webhook_secret", "token-sintetico-crm16c")
    monkeypatch.setattr(settings, "virtualpos_payout_webhook_secret", "hmac-sintetico-crm16c")
    client = TestClient(app, base_url="https://testserver", raise_server_exceptions=False)
    body = {"id": "evt_sintetico", "event_type": "subscription.updated"}
    assert client.post("/api/v1/webhooks/toku", json=body).status_code == 401
    assert client.post("/api/v1/webhooks/payku/subscription?k=malo", json=body).status_code == 401
    assert client.post("/api/v1/webhooks/virtualpos/payout", json=body).status_code == 401
