"""Remove payment credentials before any provider payload reaches central storage."""

from __future__ import annotations

import re
from typing import Any

_SENSITIVE = {
    "account_number", "api_key", "authorization", "auth_code", "bank_account_number", "bin", "card_number", "card_pan",
    "card_token", "cavv", "cvc", "cvv", "mac", "pan", "password",
    "private_token", "secret", "secret_key", "security_code", "sign",
    "numero_cuenta", "signature", "token", "verification_key",
}


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def sanitize_payload(value: Any) -> Any:
    """Recursively retain useful provider data without payment credentials."""
    if isinstance(value, dict):
        return {
            key: sanitize_payload(nested)
            for key, nested in value.items()
            if _key(str(key)) not in _SENSITIVE
        }
    if isinstance(value, list):
        return [sanitize_payload(item) for item in value]
    return value
