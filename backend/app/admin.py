"""Offline provisioning. Password is prompted, never passed on the command line."""
import argparse
import getpass
import secrets
import re
from datetime import datetime, timedelta, timezone
from sqlalchemy import delete
from app.core.security import ROLES, password_hash, token_hash
from app.db.platform import AuditEntry, LoginSession, User
from app.db.session import SessionLocal

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["create-user", "disable-user", "machine-token"])
    parser.add_argument("username")
    parser.add_argument("--role", choices=sorted(ROLES), default="dispatcher")
    args = parser.parse_args()
    name = args.username.casefold()
    if not re.fullmatch(r"[\w.@-]{1,100}", name):
        raise SystemExit("Invalid username")
    password = None
    if args.action == "create-user":
        password = password_hash(getpass.getpass("Password (12+ characters): "))
    token = None
    with SessionLocal.begin() as db:
        user = db.get(User, name)
        if args.action == "create-user":
            if user:
                raise SystemExit("User exists; disable/reprovision through an approved administrative process")
            db.add(User(username=name, password_hash=password, role=args.role, active=True, provider="local"))
        elif args.action == "disable-user":
            if not user:
                raise SystemExit("Unknown user")
            user.active = False
            db.execute(delete(LoginSession).where(LoginSession.username == name))
        else:
            if not user or user.role != "integrator" or not user.active:
                raise SystemExit("An active integrator account is required")
            token = secrets.token_urlsafe(48)
            db.add(LoginSession(token_hash=token_hash(token), username=name,
                                csrf_token=secrets.token_urlsafe(32),
                                expires_at=datetime.now(timezone.utc) + timedelta(hours=24)))
        db.add(AuditEntry(request_id=secrets.token_hex(16), actor="offline-administrator",
                          action=args.action, target=name, outcome=200))
    print(token if token else "Done")

if __name__ == "__main__":
    main()
