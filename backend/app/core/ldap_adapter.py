"""Read-only LDAPS adapter; no anonymous bind or local fallback."""
import ssl
from ldap3 import Connection, Server, Tls
from ldap3.utils.conv import escape_filter_chars
from app.core.config import get_settings

def authenticate_ldap(username: str, password: str) -> str | None:
    s = get_settings()
    if not password:
        return None
    server = Server(s.ldap_host, port=s.ldap_port, use_ssl=True, connect_timeout=5,
                    tls=Tls(validate=ssl.CERT_REQUIRED, ca_certs_file=s.ldap_ca_file))
    service = Connection(server, user=s.ldap_bind_dn, password=s.ldap_bind_password,
                         auto_bind=True, receive_timeout=5, raise_exceptions=True, auto_referrals=False, read_only=True)
    try:
        service.search(s.ldap_base_dn, f"({s.ldap_user_attribute}={escape_filter_chars(username)})",
                       attributes=["memberOf"], size_limit=2)
        if len(service.entries) != 1:
            return None
        entry = service.entries[0]
        groups = {str(g).casefold() for g in entry.memberOf.values}
        roles = [role for group, role in s.ldap_role_groups.items() if group.casefold() in groups]
        role = next((r for r in ("admin", "dispatcher", "analyst", "technician", "manager") if r in roles), None)
        if role is None:
            return None
        user = Connection(server, user=entry.entry_dn, password=password, receive_timeout=5, auto_referrals=False, read_only=True)
        try:
            return role if user.bind() else None
        finally:
            user.unbind()
    finally:
        service.unbind()
