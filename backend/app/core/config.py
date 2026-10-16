from __future__ import annotations

import json
from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def normalize_database_url(value: str, require_ssl: bool = False) -> str:
    parsed = make_url(value)
    if parsed.drivername in {"postgres", "postgresql", "postgresql+psycopg2"}:
        parsed = parsed.set(drivername="postgresql+psycopg")
    if require_ssl and parsed.drivername.startswith("postgresql"):
        query = dict(parsed.query)
        query["sslmode"] = "require"
        parsed = parsed.set(query=query)
    return parsed.render_as_string(hide_password=False)


class Settings(BaseSettings):
    app_name: str = "Enterprise RAG Assistant"
    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 8
    database_url: str = "sqlite:///./enterprise_rag.db"
    supabase_db_url: str | None = None
    bootstrap_admin_password: str | None = None
    backend_cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    llm_provider: str = "gemini"
    grok_api_key: str | None = None
    grok_model: str = "grok-3-mini"
    grok_api_url: str = "https://api.x.ai/v1/chat/completions"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    gemini_api_url: str = "https://generativelanguage.googleapis.com/v1beta"
    google_api_key: str | None = Field(default=None, validation_alias="GOOGLE_API_KEY")
    embedding_provider: str = "gemini"
    embedding_model: str = "models/gemini-embedding-001"
    debug: bool = True

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origins(self) -> List[str]:
        stripped = self.backend_cors_origins.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError as error:
                raise ValueError("BACKEND_CORS_ORIGINS must be a comma-separated list or JSON array") from error
            if not isinstance(value, list):
                raise ValueError("BACKEND_CORS_ORIGINS JSON value must be an array")
            if not all(isinstance(origin, str) for origin in value):
                raise ValueError("BACKEND_CORS_ORIGINS entries must be strings")
            return [origin.strip() for origin in value if origin.strip()]
        return [origin.strip() for origin in stripped.split(",") if origin.strip()]

    @property
    def embedding_api_key(self) -> str | None:
        return self.google_api_key or self.gemini_api_key

    @property
    def active_database_url(self) -> str:
        if self.supabase_db_url and self.supabase_db_url.strip():
            url = self.supabase_db_url.strip()
            if not url.lower().startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
                raise ValueError(
                    "SUPABASE_DB_URL must be a PostgreSQL connection string from Supabase "
                    "(postgresql:// or postgresql+psycopg://), not the project HTTPS API URL."
                )
            return normalize_database_url(url, require_ssl=True)
        return normalize_database_url(self.database_url)


settings = Settings()
