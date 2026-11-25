"""Domain-separated private JSON records; no executable artifact deserialization."""

import hashlib
import hmac
import re

from app.ml.dataset_export import canonical_json, signature
from app.ml.export_snapshot import parse_json


def seal(value: dict, *, secret: bytes, domain: str, id_field: str) -> bytes:
    body = dict(value)
    if "signature" in body or id_field in body:
        raise ValueError("Registro ya firmado")
    body[id_field] = hashlib.sha256(canonical_json(body)).hexdigest()
    body["signature"] = signature(canonical_json(body), secret, domain=domain)
    return canonical_json(body)


def unseal(data: bytes, *, secret: bytes, domain: str, id_field: str) -> dict:
    body = parse_json(data)
    if type(body) is not dict:
        raise ValueError("Registro invalido")
    mac = body.pop("signature", None)
    if (not isinstance(mac, str) or not re.fullmatch(r"[a-f0-9]{64}", mac)
            or not hmac.compare_digest(mac, signature(canonical_json(body), secret, domain=domain))):
        raise ValueError("Firma invalida")
    identity = body.pop(id_field, None)
    if identity != hashlib.sha256(canonical_json(body)).hexdigest():
        raise ValueError("Fingerprint invalido")
    return body | {id_field: identity}
