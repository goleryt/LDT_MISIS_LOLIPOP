from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "LDT MISIS LOLIPOP Backend"
    app_version: str = "0.1.0"

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "ldt_misis"
    postgres_user: str = "ldt_user"
    postgres_password: str

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://"
            f"{self.postgres_user}:"
            f"{self.postgres_password}@"
            f"{self.postgres_host}:"
            f"{self.postgres_port}/"
            f"{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()