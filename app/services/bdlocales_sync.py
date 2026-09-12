"""Sync desde APIs de proveedores hacia las BDlocales (PostgreSQL locales).

Puerto del BDlocales/sync.py sin CLI ni tqdm; integrado con config del CRM.
Flujo: API proveedor → INSERT/UPDATE en BDlocales PostgreSQL.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import psycopg
import requests
from psycopg import sql
from psycopg.types.json import Jsonb

from app.core.config import settings

logger = logging.getLogger(__name__)

_SYSTEM_COLUMNS = {"platform", "remote_id", "raw_payload", "synced_at"}
_URL_COMPONENT_SAFE = "~()*!.'"
_HTTP_SESSION = requests.Session()

# ─── Configs de tablas (portadas de configs/*.json) ───────────────────────────

_VP_ACCOUNTS = [
    {
        "platform": "virtualPOS1",
        "base_url": settings.virtualpos_base_url,
        "api_key": settings.virtualpos_api_key,
        "secret_key": settings.virtualpos_secret_key,
    },
    {
        "platform": "virtualPOS2",
        "base_url": settings.virtualpos2_base_url,
        "api_key": settings.virtualpos2_api_key,
        "secret_key": settings.virtualpos2_secret_key,
    },
]

_VP_TABLES: dict[str, dict] = {
    "cliente": {
        "path": "/v3/clients",
        "params": {"limit": 100, "page": 1},
        "pagination": {"page_param": "page", "page_size_param": "limit"},
        "id_fields": ["client_uuid", "uuid", "id"],
    },
    "plan": {
        "path": "/v3/plans",
        "id_fields": ["plan_id", "id"],
    },
    "subscripcion": {
        "path": "/v3/suscriptions",
        "params": {"limit": 100, "page": 1},
        "pagination": {"page_param": "page", "page_size_param": "limit"},
        "id_fields": ["suscription_id", "subscription_id", "id"],
    },
    "cargos": {
        "path": "/v3/suscription/{suscription_id}/charges",
        "parent_table": "subscripcion",
        "parent_id_fields": ["suscription_id", "subscription_id", "id"],
        "params": {"limit": 100, "page": 1},
        "pagination": {"page_param": "page", "page_size_param": "limit"},
        "id_fields": ["charge_id", "id"],
    },
    "transacciones": {
        "path": "/v3/payments",
        "params": {"limit": 100, "page": 1},
        "pagination": {"page_param": "page", "page_size_param": "limit"},
        "id_fields": ["order.uuid", "payment_uuid", "transaction_id", "id"],
    },
}

_TOKU_TABLES: dict[str, dict] = {
    "customer": {
        "path": "/customers",
        "params": {"page_size": 100},
        "pagination": {"type": "cursor", "cursor_param": "next_cursor", "cursor_response_field": "next_cursor"},
        "id_fields": ["id", "customer_id", "external_id"],
    },
    "payment_method": {
        "path": "/payment-methods",
        "params": {"page": 1, "page_size": 100},
        "pagination": {"page_param": "page", "page_size_param": "page_size"},
        "id_fields": ["payment_method.id", "id", "payment_method_id"],
    },
    "subscription": {
        "path": "/subscriptions",
        "params": {"page_size": 100},
        "pagination": {"type": "cursor", "cursor_param": "next_cursor", "cursor_response_field": "next_cursor"},
        "id_fields": ["id", "subscription_id", "product_id"],
    },
    "invoices": {
        "path": "/invoices",
        "params": {"page_size": 100},
        "pagination": {"type": "cursor", "cursor_param": "next_cursor", "cursor_response_field": "next_cursor"},
        "id_fields": ["id", "invoice_id", "invoice_external_id"],
    },
    "payment": {
        "path": "/transactions",
        "params": {"page": 1, "page_size": 100},
        "pagination": {"page_param": "page", "page_size_param": "page_size"},
        "id_fields": ["transaction.id", "id", "transaction_id"],
    },
}

_PAYKU_TABLES: dict[str, dict] = {
    "cliente": {
        "path": "/api/suclient/customers",
        "params": {"page": 1, "per_page": 100},
        "pagination": {"page_param": "page", "page_size_param": "per_page"},
        "id_fields": ["id", "client_id"],
    },
    "plan": {
        "path": "/api/suplan/plans",
        "id_fields": ["id", "plan_id"],
    },
    "subscripcion": {
        "path": "/api/sususcriptionv3",
        "params": {"page": 1, "per_page": 100},
        "pagination": {"page_param": "page", "page_size_param": "per_page"},
        "id_fields": ["id", "subscription_id"],
    },
    "transaccion": {
        "path": "/api/transaction",
        "params": {"page": 1, "per_page": 100, "success": "true", "rejected": "true"},
        "pagination": {"page_param": "page", "page_size_param": "per_page"},
        "exclude_statuses": ["pending"],
        "id_fields": ["id", "transaction_id", "order"],
    },
}


# ─── Auth ─────────────────────────────────────────────────────────────────────

def _jwt_signature(api_key: str, secret_key: str) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=")
    payload = base64.urlsafe_b64encode(
        json.dumps({"api_key": api_key}, separators=(",", ":")).encode()
    ).rstrip(b"=")
    signed = header + b"." + payload
    signature = hmac.new(secret_key.encode(), signed, hashlib.sha256).digest()
    return (signed + b"." + base64.urlsafe_b64encode(signature).rstrip(b"=")).decode()


def _auth_headers_vp(account: dict, path: str, params: dict) -> dict:
    api_key = account["api_key"]
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": api_key,
        "Signature": _jwt_signature(api_key, account["secret_key"]),
    }


def _auth_headers_toku(path: str, params: dict) -> dict:
    headers: dict = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "x-api-key": settings.toku_api_key,
    }
    if settings.toku_account_key:
        headers["x-account-key"] = settings.toku_account_key
    return headers


def _auth_headers_payku(path: str, params: dict) -> dict:
    public_token = settings.payku_public_token or settings.payku_api_key
    private_token = settings.payku_private_token or settings.payku_secret_key
    scalar_params = {k: v for k, v in params.items() if v is not None and not isinstance(v, (dict, list))}
    encoded_path = quote(path, safe=_URL_COMPONENT_SAFE)
    pairs = [
        f"{quote(str(k), safe=_URL_COMPONENT_SAFE)}={quote(str(v), safe=_URL_COMPONENT_SAFE).replace('%20', '+')}"
        for k, v in sorted(scalar_params.items())
    ]
    signing_input = "&".join([encoded_path, *pairs])
    sign = hmac.new(private_token.encode(), signing_input.encode(), hashlib.sha256).hexdigest()
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {public_token}",
        "Sign": sign,
    }


# ─── HTTP ─────────────────────────────────────────────────────────────────────

def _request_page(base_url: str, path: str, params: dict, headers: dict, auth_kind: str) -> Any:
    response = None
    for attempt in range(1, 6):
        try:
            response = _HTTP_SESSION.get(base_url + path, params=params, headers=headers, timeout=60)
            if response.status_code not in {429, 500, 502, 503, 504}:
                break
        except (requests.ConnectionError, requests.Timeout):
            if attempt == 5:
                raise
            logger.warning("Error temporal al consultar %s. Reintento %d/5.", path, attempt + 1)
        if attempt < 5:
            time.sleep(2 ** (attempt - 1))
    if response is None:
        raise requests.ConnectionError(f"No fue posible consultar {path}")
    if auth_kind == "payku" and response.status_code in {401, 403}:
        raise ValueError("Payku rechazó la autenticación. Verifica tokens y ambiente (sandbox vs producción).")
    response.raise_for_status()
    payload = response.json()
    if auth_kind == "virtualpos" and isinstance(payload, dict) and "error" in payload:
        raise _RemoteLogicalError("VirtualPOS devolvió un error lógico para este recurso")
    if auth_kind == "payku":
        if isinstance(payload, dict) and payload.get("type") == "there are no records":
            return []
        if isinstance(payload, dict) and payload.get("status") not in (None, "success", "SUCCESS", 200):
            raise ValueError(f"Payku devolvió un error lógico: {payload}")
    return payload


class _RemoteLogicalError(ValueError):
    pass


# ─── Extracción de registros ──────────────────────────────────────────────────

def _extract_records(payload: Any, table_name: str) -> list:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    candidates = ["data", "items", "results", "records", table_name, f"{table_name}s"]
    for key in candidates:
        if isinstance(payload.get(key), list):
            return payload[key]
    list_values = [v for v in payload.values() if isinstance(v, list)]
    if len(list_values) == 1:
        return list_values[0]
    return [payload]


def _accepted_records(table_config: dict, records: list) -> list:
    excluded = set(table_config.get("exclude_statuses", []))
    if not excluded:
        return records
    return [r for r in records if r.get("status") not in excluded]


# ─── Identificador de registro ────────────────────────────────────────────────

def _identifier(record: dict, id_fields: list[str]) -> str:
    for field in id_fields:
        value = record
        for segment in field.split("."):
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(segment)
        if value is not None:
            return str(value)
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode()).hexdigest()


# ─── DDL sobre BDlocales ──────────────────────────────────────────────────────

def _normalise_column(path: tuple[str, ...]) -> str:
    name = "__".join(path).lower()
    name = re.sub(r"[^a-z0-9_]+", "_", name).strip("_") or "field"
    if name[0].isdigit() or name in _SYSTEM_COLUMNS:
        name = f"field_{name}"
    return name[:60]


def _flatten_fields(value: Any, path: tuple[str, ...] = ()) -> list[tuple[str, Any]]:
    if not isinstance(value, dict):
        return []
    fields = []
    for key, item in value.items():
        item_path = (*path, str(key))
        fields.append((_normalise_column(item_path), item))
        if isinstance(item, dict):
            fields.extend(_flatten_fields(item, item_path))
    return fields


def _records_columns(records: list) -> set[str]:
    columns: set[str] = set()
    for record in records:
        if isinstance(record, dict):
            columns.update(col for col, _ in _flatten_fields(record))
    return columns


def _table_columns(conn: psycopg.Connection, table_name: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = %s",
            (table_name,),
        )
        return {row[0] for row in cur.fetchall()}


def _ensure_table(conn: psycopg.Connection, table_name: str, has_platform: bool = False) -> None:
    with conn.cursor() as cur:
        if has_platform:
            cur.execute(
                sql.SQL(
                    "CREATE TABLE IF NOT EXISTS {} "
                    "(platform TEXT NOT NULL, remote_id TEXT NOT NULL, "
                    "raw_payload JSONB NOT NULL, synced_at TIMESTAMPTZ NOT NULL, "
                    "PRIMARY KEY (platform, remote_id))"
                ).format(sql.Identifier(table_name))
            )
        else:
            cur.execute(
                sql.SQL(
                    "CREATE TABLE IF NOT EXISTS {} "
                    "(remote_id TEXT PRIMARY KEY, raw_payload JSONB NOT NULL, synced_at TIMESTAMPTZ NOT NULL)"
                ).format(sql.Identifier(table_name))
            )


def _ensure_columns(conn: psycopg.Connection, table_name: str, columns: set[str]) -> None:
    with conn.cursor() as cur:
        for column in columns:
            cur.execute(
                sql.SQL("ALTER TABLE {} ADD COLUMN IF NOT EXISTS {} JSONB").format(
                    sql.Identifier(table_name), sql.Identifier(column)
                )
            )


def _upsert(
    conn: psycopg.Connection,
    table_name: str,
    record: dict,
    id_fields: list[str],
    platform: str | None = None,
) -> None:
    fields = dict(_flatten_fields(record))
    values: dict[str, Any] = {
        "remote_id": _identifier(record, id_fields),
        "raw_payload": Jsonb(record),
        "synced_at": datetime.now(timezone.utc),
    }
    if platform:
        values["platform"] = platform
    values.update({col: Jsonb(val) for col, val in fields.items()})
    columns = list(values)
    conflict_cols = ["platform", "remote_id"] if platform else ["remote_id"]
    assignments = [
        sql.SQL("{} = EXCLUDED.{}").format(sql.Identifier(c), sql.Identifier(c))
        for c in columns if c not in conflict_cols
    ]
    stmt = sql.SQL(
        "INSERT INTO {} ({}) VALUES ({}) ON CONFLICT ({}) DO UPDATE SET {}"
    ).format(
        sql.Identifier(table_name),
        sql.SQL(", ").join(map(sql.Identifier, columns)),
        sql.SQL(", ").join(sql.Placeholder(c) for c in columns),
        sql.SQL(", ").join(map(sql.Identifier, conflict_cols)),
        sql.SQL(", ").join(assignments),
    )
    with conn.cursor() as cur:
        cur.execute(stmt, values)


# ─── Loop de paginación ───────────────────────────────────────────────────────

def _dsn(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://")


def _sync_table(
    conn: psycopg.Connection,
    table_name: str,
    table_config: dict,
    base_url: str,
    auth_kind: str,
    account: dict | None = None,
) -> int:
    _ensure_table(conn, table_name, has_platform=account is not None)
    if "parent_table" in table_config:
        return _sync_child_table(conn, table_name, table_config, base_url, auth_kind, account)

    params = dict(table_config.get("params", {}))
    pagination = table_config.get("pagination")
    total = 0
    known_columns = _table_columns(conn, table_name)

    while True:
        headers = _get_headers(auth_kind, table_config["path"], params, account)
        payload = _request_page(base_url, table_config["path"], params, headers, auth_kind)
        page_records = _extract_records(payload, table_name)
        records = _accepted_records(table_config, page_records)
        missing = _records_columns(records) - known_columns
        if missing:
            _ensure_columns(conn, table_name, missing)
            known_columns.update(missing)
        for record in records:
            _upsert(conn, table_name, record, table_config["id_fields"], account["platform"] if account else None)
            total += 1
        conn.commit()

        if not pagination or not page_records:
            break
        if pagination.get("type") == "cursor":
            cursor = payload.get(pagination["cursor_response_field"]) if isinstance(payload, dict) else None
            if not cursor:
                break
            params[pagination["cursor_param"]] = cursor
            time.sleep(0.2)
            continue
        page_param = pagination["page_param"]
        page_size = int(params.get(pagination["page_size_param"], len(page_records)))
        metadata = payload.get("pagination") if isinstance(payload, dict) else None
        if isinstance(metadata, dict):
            try:
                if int(metadata.get(page_param, 0)) >= int(metadata.get("pages", 0)):
                    break
            except (TypeError, ValueError):
                pass
        if len(page_records) < page_size:
            break
        params[page_param] = int(params.get(page_param, 1)) + 1
        time.sleep(0.2)

    return total


def _sync_child_table(
    conn: psycopg.Connection,
    table_name: str,
    table_config: dict,
    base_url: str,
    auth_kind: str,
    account: dict | None = None,
) -> int:
    parent = table_config["parent_table"]
    with conn.cursor() as cur:
        query = sql.SQL("SELECT raw_payload FROM {}").format(sql.Identifier(parent))
        if account:
            query += sql.SQL(" WHERE platform = %s")
            cur.execute(query, (account["platform"],))
        else:
            cur.execute(query)
        parents = [row[0] for row in cur.fetchall()]

    total = 0
    skipped = 0
    known_columns = _table_columns(conn, table_name)

    for parent_record in parents:
        parent_id = _identifier(parent_record, table_config["parent_id_fields"])
        path = table_config["path"].format(suscription_id=parent_id)
        params = dict(table_config.get("params", {}))
        pagination = table_config.get("pagination")

        while True:
            try:
                headers = _get_headers(auth_kind, path, params, account)
                payload = _request_page(base_url, path, params, headers, auth_kind)
            except _RemoteLogicalError:
                skipped += 1
                break
            records = _extract_records(payload, table_name)
            missing = _records_columns(records) - known_columns
            if missing:
                _ensure_columns(conn, table_name, missing)
                known_columns.update(missing)
            for record in records:
                if "suscription_id" not in record:
                    record = {"suscription_id": parent_id, **record}
                    if "suscription_id" not in known_columns:
                        _ensure_columns(conn, table_name, {"suscription_id"})
                        known_columns.add("suscription_id")
                _upsert(conn, table_name, record, table_config["id_fields"], account["platform"] if account else None)
                total += 1
            conn.commit()
            if not pagination:
                break
            page_size = int(params.get(pagination["page_size_param"], len(records)))
            if len(records) < page_size:
                break
            params[pagination["page_param"]] = int(params.get(pagination["page_param"], 1)) + 1
            time.sleep(0.2)

    if skipped:
        logger.info("Cargos omitidos: %d suscripciones sin respuesta sincronizable.", skipped)
    return total


def _get_headers(auth_kind: str, path: str, params: dict, account: dict | None) -> dict:
    if auth_kind == "virtualpos" and account:
        return _auth_headers_vp(account, path, params)
    if auth_kind == "toku":
        return _auth_headers_toku(path, params)
    if auth_kind == "payku":
        return _auth_headers_payku(path, params)
    raise ValueError(f"Auth desconocido: {auth_kind}")


# ─── Funciones públicas ───────────────────────────────────────────────────────

def sync_virtualpos(tables: list[str] | None = None) -> dict[str, int]:
    """Sync desde APIs VirtualPOS (cuentas 1 y 2) hacia VirtualPOS_Local."""
    dsn = _dsn(settings.virtualpos_db_url)
    selected = tables or list(_VP_TABLES)
    counts: dict[str, int] = {}
    accounts = [a for a in _VP_ACCOUNTS if a["api_key"] and a["secret_key"] and a["base_url"]]

    with psycopg.connect(dsn) as conn:
        for table_name in selected:
            table_config = _VP_TABLES[table_name]
            for account in accounts:
                key = f"{table_name}_{account['platform']}"
                try:
                    n = _sync_table(conn, table_name, table_config, account["base_url"], "virtualpos", account)
                    counts[key] = n
                    logger.info("VirtualPOS %s %s: %d registros", account["platform"], table_name, n)
                except Exception:
                    logger.exception("Error sincronizando VirtualPOS %s %s", account["platform"], table_name)
                    counts[key] = 0
    return counts


def sync_toku(tables: list[str] | None = None) -> dict[str, int]:
    """Sync desde API Toku hacia Toku_Local."""
    if not settings.toku_api_key or not settings.toku_base_url:
        logger.warning("Toku no configurado (TOKU_API_KEY o TOKU_BASE_URL vacíos). Omitido.")
        return {}
    dsn = _dsn(settings.toku_db_url)
    selected = tables or list(_TOKU_TABLES)
    counts: dict[str, int] = {}

    with psycopg.connect(dsn) as conn:
        for table_name in selected:
            table_config = _TOKU_TABLES[table_name]
            try:
                n = _sync_table(conn, table_name, table_config, settings.toku_base_url, "toku")
                counts[table_name] = n
                logger.info("Toku %s: %d registros", table_name, n)
            except Exception:
                logger.exception("Error sincronizando Toku %s", table_name)
                counts[table_name] = 0
    return counts


def sync_payku(tables: list[str] | None = None) -> dict[str, int]:
    """Sync desde API Payku hacia Payku_Local."""
    public = settings.payku_public_token or settings.payku_api_key
    private = settings.payku_private_token or settings.payku_secret_key
    if not public or not private or not settings.payku_base_url:
        logger.warning("Payku no configurado (tokens o PAYKU_BASE_URL vacíos). Omitido.")
        return {}

    # Inyectar rango de fechas en params de tablas que los usan
    payku_tables = _build_payku_tables()
    dsn = _dsn(settings.payku_db_url)
    selected = tables or list(payku_tables)
    counts: dict[str, int] = {}

    with psycopg.connect(dsn) as conn:
        for table_name in selected:
            table_config = payku_tables[table_name]
            try:
                n = _sync_table(conn, table_name, table_config, settings.payku_base_url, "payku")
                counts[table_name] = n
                logger.info("Payku %s: %d registros", table_name, n)
            except Exception:
                logger.exception("Error sincronizando Payku %s", table_name)
                counts[table_name] = 0
    return counts


def _build_payku_tables() -> dict[str, dict]:
    """Crea configs de tablas Payku con rango de fechas del entorno."""
    date_init = settings.payku_date_init or "2020-08-04"
    date_end = settings.payku_date_end or datetime.now(timezone.utc).date().isoformat()
    tables: dict[str, dict] = {}
    for name, cfg in _PAYKU_TABLES.items():
        entry = dict(cfg)
        if name in ("subscripcion", "transaccion"):
            params = dict(cfg.get("params", {}))
            params["date_init"] = date_init
            params["date_end"] = date_end
            entry["params"] = params
        tables[name] = entry
    return tables
