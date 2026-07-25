"""Auth: scrypt password hashing + HMAC-signed session cookies. Stdlib only.

Set SECRET_KEY in production; without it a per-process random key is used and
sessions reset on restart.
"""
import base64
import hashlib
import hmac
import os
import re
import secrets
import time

from fastapi import Depends, HTTPException, Request, Response

import db

SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
SESSION_TTL = 30 * 24 * 3600  # 30 days
COOKIE_NAME = "pdt_session"
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "").lower() in ("1", "true")

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{3,32}$")


# ---------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$")
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------- sessions
def _sign(payload: str) -> str:
    return hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()


def create_token(user_id: int) -> str:
    payload = f"{user_id}.{int(time.time()) + SESSION_TTL}"
    encoded = base64.urlsafe_b64encode(payload.encode()).decode()
    return f"{encoded}.{_sign(payload)}"


def verify_token(token: str) -> int | None:
    try:
        encoded, sig = token.rsplit(".", 1)
        payload = base64.urlsafe_b64decode(encoded.encode()).decode()
        if not hmac.compare_digest(sig, _sign(payload)):
            return None
        user_id, expiry = payload.split(".")
        if time.time() > int(expiry):
            return None
        return int(user_id)
    except (ValueError, TypeError):
        return None


def set_session_cookie(response: Response, user_id: int) -> None:
    response.set_cookie(
        COOKIE_NAME, create_token(user_id),
        max_age=SESSION_TTL, httponly=True, samesite="lax", secure=COOKIE_SECURE,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME)


# ---------------------------------------------------------------- dependencies
def current_user(request: Request) -> dict | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    user_id = verify_token(token)
    if user_id is None:
        return None
    row = db.get_user_by_id(user_id)
    if row is None:
        return None
    return {"id": row["id"], "username": row["username"], "is_admin": bool(row["is_admin"])}


def require_user(user: dict | None = Depends(current_user)) -> dict:
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in required")
    return user


def require_admin(user: dict = Depends(require_user)) -> dict:
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin only")
    return user
