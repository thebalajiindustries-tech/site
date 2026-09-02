"""Email+password auth using only the Python standard library.

- Passwords: PBKDF2-HMAC-SHA256 with a per-user random salt.
- Sessions:  a compact HMAC-signed token (mini-JWT), verified on every request.

Swappable for passlib / PyJWT in production; the interface stays the same.
"""
import base64
import hashlib
import hmac
import json
import os
import time

from fastapi import Header, HTTPException

from .config import get_settings
from . import tenancy

settings = get_settings()
_ROUNDS = 200_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ROUNDS)
    return f"pbkdf2_sha256${_ROUNDS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _algo, rounds, salt_hex, hash_hex = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(body: str) -> str:
    return _b64e(hmac.new(settings.AUTH_SECRET.encode(), body.encode(), hashlib.sha256).digest())


def make_token(user_id: int, tenant_id: int, email: str) -> str:
    payload = {
        "uid": user_id,
        "tid": tenant_id,
        "email": email,
        "exp": int(time.time()) + settings.TOKEN_TTL_SECONDS,
    }
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode())
    return f"{body}.{_sign(body)}"


def verify_token(token: str) -> dict:
    try:
        body, sig = token.split(".")
    except ValueError:
        raise HTTPException(401, "Malformed token.")
    if not hmac.compare_digest(sig, _sign(body)):
        raise HTTPException(401, "Invalid session. Please log in again.")
    payload = json.loads(_b64d(body))
    if payload.get("exp", 0) < time.time():
        raise HTTPException(401, "Session expired. Please log in again.")
    return payload


def current_user(authorization: str = Header(default="")) -> dict:
    """FastAPI dependency: resolves the caller to {user, tenant} or raises 401."""
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Not authenticated.")
    payload = verify_token(authorization[7:].strip())
    user = tenancy.get_user(payload["uid"])
    if not user:
        raise HTTPException(401, "User no longer exists.")
    tenant = tenancy.get_tenant(user["tenant_id"])
    if not tenant:
        raise HTTPException(401, "Company not found.")
    return {"user": user, "tenant": tenant}
