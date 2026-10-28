"""Service configuration, read once from environment variables (see .env.example)."""
import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in ("1", "true", "yes")


def _list(name: str, default: str) -> list[str]:
    return [x.strip() for x in os.environ.get(name, default).split(",") if x.strip()]


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.environ.get("DATABASE_URL", "sqlite:///./lectura-dev.db"))

    # Same values as api-colegio-smart: the JWT in the cs_session cookie is issued there.
    jwt_secret: str = field(default_factory=lambda: os.environ.get("JWT_SECRET", ""))
    jwt_issuer: str = field(default_factory=lambda: os.environ.get("JWT_ISSUER", "colegio-smart-api"))
    jwt_audience: str = field(default_factory=lambda: os.environ.get("JWT_AUDIENCE", "colegio-smart-app"))
    auth_cookie_name: str = field(default_factory=lambda: os.environ.get("AUTH_COOKIE_NAME", "cs_session"))
    csrf_cookie_secure: bool = field(default_factory=lambda: _bool("CSRF_COOKIE_SECURE", True))

    cors_allowed_origins: list[str] = field(
        default_factory=lambda: _list("CORS_ALLOWED_ORIGINS", "https://lectura.colegiosmart.cl"))

    # Private bucket for reading audio. Do not reuse a bucket exposed through R2_PUBLIC_BASE_URL.
    r2_account_id: str = field(default_factory=lambda: os.environ.get("R2_ACCOUNT_ID", ""))
    r2_access_key_id: str = field(default_factory=lambda: os.environ.get("R2_ACCESS_KEY_ID", ""))
    r2_secret_access_key: str = field(default_factory=lambda: os.environ.get("R2_SECRET_ACCESS_KEY", ""))
    r2_bucket: str = field(default_factory=lambda: os.environ.get("R2_READING_BUCKET", ""))
    presigned_ttl_seconds: int = field(default_factory=lambda: int(os.environ.get("PRESIGNED_TTL_SECONDS", "900")))

    # Run the analysis worker inside this process. Keep a single process: each one loads the models (~2 GB).
    worker_enabled: bool = field(default_factory=lambda: _bool("WORKER_ENABLED", True))
    worker_poll_seconds: float = field(default_factory=lambda: float(os.environ.get("WORKER_POLL_SECONDS", "1.0")))


settings = Settings()
