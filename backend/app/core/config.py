from functools import lru_cache
from typing import Literal
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

class Settings(BaseSettings):
    app_name: str = "LDT MISIS LOLIPOP Backend"
    app_version: str = "0.2.0"
    environment: Literal["development", "test", "production"] = "development"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "ldt_misis"
    postgres_user: str = "ldt_user"
    postgres_password: str
    postgres_sslmode: str = "prefer"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    max_upload_bytes: int = Field(default=50 * 1024 * 1024, ge=1024, le=200 * 1024 * 1024)
    max_import_rows: int = Field(default=250000, ge=1)
    read_cache_seconds: float = Field(default=2, ge=0, le=5)
    auth_provider: Literal["local", "ldap"] = "local"
    secure_cookies: bool = False
    session_hours: int = Field(default=8, ge=1, le=24)
    allowed_hosts: str = "localhost,127.0.0.1,testserver"
    source_timezone: str = "Europe/Moscow"
    allow_mock_ingestion: bool = False
    ldap_host: str = ""
    ldap_port: int = 636
    ldap_ca_file: str | None = None
    ldap_bind_dn: str = ""
    ldap_bind_password: str = ""
    ldap_base_dn: str = ""
    ldap_user_attribute: Literal["sAMAccountName", "uid"] = "sAMAccountName"
    ldap_role_groups: dict[str, str] = {}
    integration_sources_file: str = ""
    integration_poll_seconds: int = Field(default=30, ge=5, le=120)
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="after")
    def production_safety(self):
        if self.environment == "production":
            if not self.secure_cookies or self.allow_mock_ingestion or "*" in self.allowed_hosts:
                raise ValueError("Production requires secure cookies, explicit hosts and mock ingestion disabled")
            if len(self.postgres_password) < 16:
                raise ValueError("Production database password must contain at least 16 characters")
        if self.auth_provider == "ldap" and not (self.ldap_host and self.ldap_base_dn and self.ldap_bind_dn and self.ldap_bind_password and self.ldap_role_groups):
            raise ValueError("LDAP connection, search credentials and explicit group mapping are required")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def database_url(self) -> URL:
        return URL.create("postgresql+psycopg", username=self.postgres_user, password=self.postgres_password,
                          host=self.postgres_host, port=self.postgres_port, database=self.postgres_db,
                          query={"sslmode": self.postgres_sslmode})

@lru_cache
def get_settings() -> Settings:
    return Settings()
