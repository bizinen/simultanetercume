"""
Authentication module - JWT based simple auth for admin panel.
"""

import logging
import os
import secrets
import sys
from datetime import datetime, timedelta
from typing import Optional

from dotenv import load_dotenv
from fastapi import HTTPException, Request, status

load_dotenv()

logger = logging.getLogger(__name__)

# --- Configuration ---
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

# 2. Check if either variable is None or an empty string
if not ADMIN_USERNAME or not ADMIN_PASSWORD:
    print("ERROR: Missing required environment variables: ADMIN_USERNAME or ADMIN_PASSWORD.")
    sys.exit(1)  # Stop execution with a non-zero exit code

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not JWT_SECRET_KEY or JWT_SECRET_KEY == "change-me-to-a-random-secret-key-32chars":
    logger.error(
        "🔴 JWT_SECRET_KEY .env dosyasında ayarlanmamış! "
        "Geçici rastgele secret oluşturuluyor — her yeniden başlatmada oturumlar sıfırlanır. "
        "Production ortamında JWT_SECRET_KEY mutlaka ayarlanmalıdır."
    )
    JWT_SECRET_KEY = secrets.token_urlsafe(32)

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24

# --- Rate Limiting ---
MAX_LOGIN_ATTEMPTS = 5           # Max failed attempts before lockout
LOCKOUT_DURATION_SECS = 86400    # 24 hours in seconds

# In-memory failed login tracker: { ip: { "count": int, "first_fail": datetime, "locked_until": datetime|None } }
_login_attempts: dict = {}


class LoginRateLimiter:
    """IP-based brute-force protection for login endpoint."""

    @staticmethod
    def check(ip: str) -> tuple[bool, str]:
        """Check if IP is allowed to attempt login.
        Returns (allowed: bool, message: str).
        """
        record = _login_attempts.get(ip)
        if not record:
            return True, ""

        # Check lockout
        if record.get("locked_until"):
            now = datetime.utcnow()
            if now < record["locked_until"]:
                remaining = record["locked_until"] - now
                hours = int(remaining.total_seconds() // 3600)
                minutes = int((remaining.total_seconds() % 3600) // 60)
                return False, f"Çok fazla başarısız deneme. {hours} saat {minutes} dakika sonra tekrar deneyin."
            else:
                # Lockout expired, reset
                del _login_attempts[ip]
                return True, ""

        return True, ""

    @staticmethod
    def record_failure(ip: str) -> tuple[int, bool]:
        """Record a failed login attempt.
        Returns (remaining_attempts: int, is_locked: bool).
        """
        now = datetime.utcnow()
        record = _login_attempts.get(ip)

        if not record:
            _login_attempts[ip] = {"count": 1, "first_fail": now, "locked_until": None}
            return MAX_LOGIN_ATTEMPTS - 1, False

        # Reset if first failure was more than 24h ago (sliding window)
        if (now - record["first_fail"]).total_seconds() > LOCKOUT_DURATION_SECS:
            _login_attempts[ip] = {"count": 1, "first_fail": now, "locked_until": None}
            return MAX_LOGIN_ATTEMPTS - 1, False

        record["count"] += 1

        if record["count"] >= MAX_LOGIN_ATTEMPTS:
            record["locked_until"] = now + timedelta(seconds=LOCKOUT_DURATION_SECS)
            return 0, True

        return MAX_LOGIN_ATTEMPTS - record["count"], False

    @staticmethod
    def reset(ip: str) -> None:
        """Reset failed attempts on successful login."""
        _login_attempts.pop(ip, None)

# Lazy imports - jwt/passlib may not be installed yet
_jwt = None
_passlib_ctx = None


def _get_jwt():
    global _jwt
    if _jwt is None:
        import jwt  # PyJWT
        _jwt = jwt
    return _jwt


def _get_pwd_context():
    global _passlib_ctx
    if _passlib_ctx is None:
        from passlib.context import CryptContext
        _passlib_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
    return _passlib_ctx


def verify_password(plain_password: str, stored_password: str) -> bool:
    """Verify password - supports both plain text and hashed passwords."""
    if not stored_password:
        return False
    # If stored password looks like a bcrypt hash, use passlib
    if stored_password.startswith("$2"):
        return _get_pwd_context().verify(plain_password, stored_password)
    # Otherwise, plain text comparison (for simplicity in .env)
    return plain_password == stored_password


def create_token(username: str) -> str:
    """Create JWT token with 24-hour expiry."""
    jwt_mod = _get_jwt()
    expire = datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS)
    payload = {
        "sub": username,
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    # PyJWT encode returns str in v2.0+, bytes in older versions. 
    # But usually we want str. If it returns bytes, decode it.
    token = jwt_mod.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    if isinstance(token, bytes):
        return token.decode("utf-8")
    return token


def verify_token(token: str) -> Optional[str]:
    """Verify JWT token and return username, or None if invalid."""
    jwt_mod = _get_jwt()
    try:
        # PyJWT raises PyJWTError on failure
        payload = jwt_mod.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return None
        return username
    except Exception:
        return None


def authenticate_user(username: str, password: str) -> bool:
    """Authenticate user credentials."""
    if username != ADMIN_USERNAME:
        return False
    return verify_password(password, ADMIN_PASSWORD)


async def get_current_user(request: Request) -> str:
    """FastAPI dependency - extract and validate JWT from request.
    
    Checks Authorization header (Bearer token) and cookie fallback.
    Raises HTTPException 401 if not authenticated.
    """
    token = None

    # 1. Check Authorization header
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]

    # 2. Fallback: check cookie
    if not token:
        token = request.cookies.get("access_token", "")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    username = verify_token(token)
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return username
