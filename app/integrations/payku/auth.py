import hashlib
import hmac
from typing import Any
from urllib.parse import quote, urlencode


def build_sign(request_path: str, values: dict[str, Any], secret_key: str) -> str:
    """Build the Payku HMAC for subscription API requests."""
    query = urlencode(
        sorted(
            (key, value)
            for key, value in values.items()
            if value is not None and not isinstance(value, (dict, list))
        )
    )
    payload = f"{quote(request_path, safe='')}&{query}"
    return hmac.new(secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
