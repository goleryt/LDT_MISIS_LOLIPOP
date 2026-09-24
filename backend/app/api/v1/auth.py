import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from app.core.config import get_settings
from app.core.security import COOKIE, token_hash, verify_password
from app.db.platform import LoginAttempt, LoginSession, User
from app.db.session import SessionLocal

router = APIRouter(prefix="/auth", tags=["authentication"])

class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=100, pattern=r"^[\w.@-]+$")
    password: str = Field(min_length=1, max_length=256)

@router.post("/login")
def login(payload: Credentials, request: Request, response: Response):
    settings = get_settings()
    origin = request.headers.get("origin")
    if origin and origin not in settings.cors_origin_list and origin != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Untrusted origin")
    now = datetime.now(timezone.utc)
    username = payload.username.casefold()
    request.state.actor = username
    # Shared DB limit works across workers. Commit attempts before checking credentials.
    key = token_hash(username)
    with SessionLocal.begin() as db:
        db.execute(insert(LoginAttempt).values(key=key, count=0, window_start=now).on_conflict_do_nothing())
        attempt = db.scalar(select(LoginAttempt).where(LoginAttempt.key == key).with_for_update())
        if now - attempt.window_start > timedelta(minutes=15):
            attempt.count, attempt.window_start = 0, now
        if attempt.count >= 10:
            raise HTTPException(429, "Too many attempts; retry after 15 minutes", headers={"Retry-After": "900"})
        attempt.count += 1
    with SessionLocal.begin() as db:
        user = db.get(User, username)
        if settings.auth_provider == "ldap":
            from app.core.ldap_adapter import authenticate_ldap
            try:
                role = authenticate_ldap(username, payload.password)
            except Exception:
                raise HTTPException(503, "Directory service unavailable") from None
            if not role or (user and not user.active):
                raise HTTPException(401, "Invalid credentials")
            if user is None:
                user = User(username=username, role=role, provider="ldap", active=True)
                db.add(user)
            elif user.provider != "ldap":
                raise HTTPException(401, "Account provider mismatch")
            user.role = role
        else:
            valid = verify_password(payload.password, user.password_hash if user else None)
            if not valid or not user or not user.active or user.provider != "local" or user.role == "integrator":
                raise HTTPException(401, "Invalid credentials")
        token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
        db.add(LoginSession(token_hash=token_hash(token), username=username, csrf_token=csrf,
                            expires_at=now + timedelta(hours=settings.session_hours)))
        db.execute(delete(LoginSession).where(LoginSession.expires_at < now))
        db.execute(delete(LoginAttempt).where(LoginAttempt.key == key))
        role = user.role
    response.set_cookie(COOKIE, token, httponly=True, secure=settings.secure_cookies, samesite="strict",
                        max_age=settings.session_hours * 3600, path="/")
    response.headers["Cache-Control"] = "no-store"
    return {"username": username, "role": role, "csrf_token": csrf}

@router.get("/me")
def me(request: Request):
    p = request.state.principal
    return {"username": p.username, "role": p.role, "csrf_token": p.csrf_token}

@router.post("/logout")
def logout(request: Request, response: Response):
    raw = request.cookies.get(COOKIE, "")
    if request.headers.get("authorization", "").startswith("Bearer "):
        raw = request.headers["authorization"][7:]
    with SessionLocal.begin() as db:
        db.execute(delete(LoginSession).where(LoginSession.token_hash == token_hash(raw)))
    response.delete_cookie(COOKIE, path="/", secure=get_settings().secure_cookies, httponly=True, samesite="strict")
    return {"status": "logged_out"}
