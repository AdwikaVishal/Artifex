"""
api/auth.py – JWT-based authentication and RBAC for Artifex.

Authentication is PostgreSQL-backed (users table) with an in-memory fallback
for development environments where the DB may not be fully initialized.

Usage
─────
  from api.auth import get_current_user, require_role, create_access_token

  @app.post("/api/login")
  async def login(creds: LoginRequest) -> TokenResponse:
      ...
      token = create_access_token(user_id="alice@example.com", role="caseworker")
      return TokenResponse(access_token=token)

  @app.get("/api/audit_logs")
  async def audit_logs(
      user: dict = Depends(require_role("admin", "supervisor")),
  ): ...

WebSocket auth
──────────────
  @app.websocket("/ws/dashboard")
  async def ws_dashboard(websocket: WebSocket, token: str = Query(...)):
      user = await verify_ws_token(token, websocket)
      if user is None:
          return  # already closed with 1008
      ...
"""

from __future__ import annotations

import os
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from fastapi import Depends, HTTPException, Query, WebSocket, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = structlog.get_logger()

# ── Configuration ─────────────────────────────────────────────────────────────

JWT_SECRET_KEY: str = os.getenv(
    "JWT_SECRET_KEY",
    "CHANGE_ME_IN_PRODUCTION_use_a_long_random_secret_key_here",
)
JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))  # 8 hours

# In-memory fallback users (used when users table is not yet migrated).
# Format: { "email": ("sha256_password", "role") }
_FALLBACK_USERS: dict[str, tuple[str, str]] = {}


def _init_fallback_users() -> None:
    """Populate fallback users from env vars (called once at import time)."""
    if _FALLBACK_USERS:
        return
    users = {
        os.getenv("ADMIN_EMAIL", "admin@artifex.local"): (
            hashlib.sha256(
                os.getenv("ADMIN_PASSWORD", "admin123").encode()
            ).hexdigest(),
            "admin",
        ),
        os.getenv("SUPERVISOR_EMAIL", "supervisor@artifex.local"): (
            hashlib.sha256(
                os.getenv("SUPERVISOR_PASSWORD", "supervisor123").encode()
            ).hexdigest(),
            "supervisor",
        ),
        os.getenv("CASEWORKER_EMAIL", "caseworker@artifex.local"): (
            hashlib.sha256(
                os.getenv("CASEWORKER_PASSWORD", "caseworker123").encode()
            ).hexdigest(),
            "caseworker",
        ),
    }
    _FALLBACK_USERS.update(users)


_init_fallback_users()

# ── Pure-Python JWT (no external library required) ────────────────────────────

import base64
import json as _json

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def create_access_token(
    user_id: str,
    role: str,
    expires_delta: timedelta | None = None,
) -> str:
    """
    Create a signed HS256 JWT containing user_id and role claims.

    Args:
        user_id:       Subject claim (email or UUID).
        role:          Role claim (admin | supervisor | caseworker).
        expires_delta: Token lifetime; defaults to JWT_EXPIRE_MINUTES.

    Returns:
        Compact JWT string (header.payload.signature).
    """
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=JWT_EXPIRE_MINUTES))

    header = {"alg": JWT_ALGORITHM, "typ": "JWT"}
    payload = {
        "sub": user_id,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }

    header_b64 = _b64url_encode(_json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64url_encode(_json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_b64}.{payload_b64}"

    sig = hmac.new(
        JWT_SECRET_KEY.encode(),
        signing_input.encode(),
        hashlib.sha256,
    ).digest()
    sig_b64 = _b64url_encode(sig)

    return f"{signing_input}.{sig_b64}"


def decode_access_token(token: str) -> dict[str, Any]:
    """
    Decode and verify a JWT.  Raises ValueError on any failure.

    Returns the payload dict on success.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid token format")

    header_b64, payload_b64, sig_b64 = parts
    signing_input = f"{header_b64}.{payload_b64}"

    # Verify signature
    expected_sig = hmac.new(
        JWT_SECRET_KEY.encode(),
        signing_input.encode(),
        hashlib.sha256,
    ).digest()
    actual_sig = _b64url_decode(sig_b64)

    if not hmac.compare_digest(expected_sig, actual_sig):
        raise ValueError("Invalid token signature")

    # Decode payload
    try:
        payload = _json.loads(_b64url_decode(payload_b64))
    except Exception as exc:
        raise ValueError(f"Cannot decode payload: {exc}") from exc

    # Check expiry
    exp = payload.get("exp")
    if exp is None or datetime.now(timezone.utc).timestamp() > exp:
        raise ValueError("Token has expired")

    return payload


# ── FastAPI dependencies ──────────────────────────────────────────────────────

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict[str, str]:
    """
    FastAPI dependency: extract and validate the Bearer JWT.

    Returns {"user_id": ..., "role": ...} on success.
    Raises HTTP 401 on missing/invalid token.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Provide a Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user_id = payload.get("sub", "")
    role = payload.get("role", "caseworker")
    logger.debug("auth.user_authenticated", user_id=user_id, role=role)
    return {"user_id": user_id, "role": role}


def require_role(*allowed_roles: str):
    """
    FastAPI dependency factory that enforces role-based access control.

    Usage:
        @app.get("/admin/only")
        async def admin_endpoint(user = Depends(require_role("admin"))):
            ...
    """
    async def _dep(user: dict = Depends(get_current_user)) -> dict[str, str]:
        if user["role"] not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Role '{user['role']}' is not permitted. "
                    f"Required: {list(allowed_roles)}"
                ),
            )
        return user

    return _dep


async def verify_ws_token(
    token: str,
    websocket: WebSocket,
) -> dict[str, str] | None:
    """
    Validate a JWT for WebSocket connections.

    Call this at the top of every WebSocket handler before accepting.
    Returns the user dict on success, or closes the socket with code 1008
    (Policy Violation) and returns None on failure.

    Usage:
        @app.websocket("/ws/dashboard")
        async def ws_dashboard(websocket: WebSocket, token: str = Query(...)):
            user = await verify_ws_token(token, websocket)
            if user is None:
                return
            await websocket.accept()
            ...
    """
    if not token:
        await websocket.close(code=1008, reason="Missing authentication token")
        return None

    try:
        payload = decode_access_token(token)
    except ValueError as exc:
        logger.warning("ws.auth.invalid_token", error=str(exc))
        await websocket.close(code=1008, reason=f"Invalid token: {exc}")
        return None

    user_id = payload.get("sub", "")
    role = payload.get("role", "caseworker")
    logger.debug("ws.auth.authenticated", user_id=user_id, role=role)
    return {"user_id": user_id, "role": role}


# ── Login helper ──────────────────────────────────────────────────────────────

async def authenticate_user(email: str, password: str) -> dict[str, str] | None:
    """
    Validate credentials against PostgreSQL users table (preferred) or the
    in-memory fallback store when the DB is not yet available.

    Returns {"user_id": email, "role": role} on success, None on failure.
    Production uses the users table (via get_user_by_email); SHA-256 is used
    for dev parity. Replace with bcrypt in production.
    """
    # 1. Try PostgreSQL first
    try:
        from api.db import get_user_by_email as _get_user, update_last_login as _update_login
        user = await _get_user(email)
        if user is not None:
            stored_hash = user.get("password_hash", "")
            provided_hash = hashlib.sha256(password.encode()).hexdigest()
            if hmac.compare_digest(stored_hash, provided_hash):
                await _update_login(email)
                return {"user_id": email, "role": user["role"]}
    except Exception:
        logger.debug("auth.db_lookup_failed_falling_back_to_memory", email=email)

    # 2. Fallback to in-memory demo users
    entry = _FALLBACK_USERS.get(email)
    if entry is None:
        return None

    stored_hash, role = entry
    provided_hash = hashlib.sha256(password.encode()).hexdigest()

    if not hmac.compare_digest(stored_hash, provided_hash):
        return None

    return {"user_id": email, "role": role}
