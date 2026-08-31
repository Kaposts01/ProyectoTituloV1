import hashlib
import hmac


def build_sign(body: str, secret_key: str) -> str:
    """HMAC-SHA256 signature of the request body for Payku /api/* write operations."""
    return hmac.new(secret_key.encode(), body.encode(), hashlib.sha256).hexdigest()
