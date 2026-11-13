from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"
    log_level: str = "INFO"
    database_url: str | None = None

    # AI (provider wiring lands in a later milestone; "mock" needs no credentials)
    llm_provider: str = "mock"
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    cors_origins: list[str] = ["http://localhost:5173"]

    @field_validator("database_url")
    @classmethod
    def _use_psycopg3_driver(cls, v: str | None) -> str | None:
        if v is None:
            return v
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v

    @property
    def is_mock_ai(self) -> bool:
        return self.llm_provider == "mock"


@lru_cache
def get_settings() -> Settings:
    return Settings()
