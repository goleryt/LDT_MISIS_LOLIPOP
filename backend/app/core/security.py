import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from fastapi import HTTPException, Request
from sqlalchemy import select
from app.db.platform import LoginSession, User
from app.db.session import SessionLocal

ROLES = {"admin", "dispatcher", "technician", "manager", "analyst", "integrator"}
COOKIE = "ldt_session"

def password_hash(password: str) -> str:
    if not 12 <= len(password) <= 256:
        raise ValueError("Password must contain 12–256 characters")
    salt = secrets.token_hex(16)
    value = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 600000).hex()
    return f"pbkdf2_sha256$600000${salt}${value}"

def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        hashlib.pbkdf2_hmac("sha256", password.encode(), b"missing-account", 600000)
        return False
    try:
        algorithm, iterations, salt, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations)).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False

def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

@dataclass(frozen=True)
class Principal:
    username: str
    role: str
    csrf_token: str

def identify(request: Request) -> Principal | None:
    token = request.cookies.get(COOKIE, "")
    bearer = request.headers.get("authorization", "")
    if bearer.startswith("Bearer "):
        token = bearer[7:]
    if not token or len(token) > 200:
        return None
    with SessionLocal() as db:
        row = db.execute(select(LoginSession, User).join(User).where(
            LoginSession.token_hash == token_hash(token), LoginSession.expires_at > datetime.now(timezone.utc),
            User.active.is_(True))).first()
        if row is None:
            return None
        session, user = row
        if bearer and user.role != "integrator":
            return None
        return Principal(user.username, user.role, session.csrf_token)

def permitted(role: str, method: str, path: str) -> bool:
    if path.startswith("/api/v1/integrations"):
        return role in {"admin", "integrator"}
    if role == "integrator":
        return path in {"/api/v1/auth/me", "/api/v1/auth/logout"}
    if path.startswith("/api/v1/admin") or path.startswith("/api/v1/audit"):
        return role == "admin"
    if method in {"GET", "HEAD"}:
        return role in ROLES
    if path == "/api/v1/auth/logout" or path.startswith("/api/v1/notifications/"):
        return role in ROLES
    if path.startswith("/api/v1/imports") or path.startswith("/api/v1/geo"):
        return role in {"admin", "dispatcher"}
    if path.startswith("/api/v1/predictions"):
        return role in {"admin", "dispatcher", "analyst"}
    if path.startswith("/api/v1/requests"):
        return role in {"admin", "dispatcher", "technician"}
    return role == "admin"

def authorize(request: Request) -> Principal:
    principal = identify(request)
    if principal is None:
        raise HTTPException(401, "Authentication required")
    request.state.actor = principal.username
    request.state.principal = principal
    if not permitted(principal.role, request.method, request.url.path):
        raise HTTPException(403, "Insufficient permissions")
    if request.method not in {"GET", "HEAD", "OPTIONS"} and not request.headers.get("authorization"):
        if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), principal.csrf_token):
            raise HTTPException(403, "Invalid CSRF token")
    return principal
