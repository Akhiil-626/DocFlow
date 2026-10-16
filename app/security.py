import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pwdlib import PasswordHash

from app.config import settings

password_hash_manager = PasswordHash.recommended()


def hash_password(password: str) -> str:
    """Hash a password using Argon2 via pwdlib."""
    return password_hash_manager.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against an Argon2 hash."""
    try:
        return password_hash_manager.verify(plain_password, hashed_password)
    except Exception:
        return False


def generate_random_token() -> str:
    """Generate a high-entropy random URL-safe token."""
    return secrets.token_urlsafe(48)


def hash_token(raw_token: str) -> str:
    """Compute deterministic SHA-256 hash for secure refresh token lookup."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_access_token(
    user_id: str,
    org_id: str,
    role: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a short-lived signed access JWT containing user_id, org_id, and role."""
    now = datetime.now(UTC)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    payload: dict[str, Any] = {
        "sub": str(user_id),
        "user_id": str(user_id),
        "org_id": str(org_id),
        "role": str(role),
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a signed access JWT."""
    return jwt.decode(
        token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
    )
