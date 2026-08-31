import base64
import hashlib
import hmac
import json


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def build_signature(api_key: str, secret_key: str) -> str:
    """Build the static HS256 JWT required by the VirtualPOS collection."""
    header = _base64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _base64url(json.dumps({"api_key": api_key}, separators=(",", ":")).encode())
    unsigned_token = f"{header}.{payload}"
    signature = hmac.new(secret_key.encode(), unsigned_token.encode(), hashlib.sha256).digest()
    return f"{unsigned_token}.{_base64url(signature)}"
