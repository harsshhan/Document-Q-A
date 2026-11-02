"""Application configuration.

Values are read from the process environment first and then from the ``.env``
file that sits next to this project, so loading does not depend on the current
working directory. Secrets are never hardcoded and never logged.
"""

import logging
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

MIN_JWT_SECRET_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "development"

    # --- Gemini (embeddings + answer generation) ---
    gemini_api_key: str | None = None
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_embedding_model: str = "gemini-embedding-001"
    gemini_chat_model: str = "gemini-2.5-flash"
    gemini_timeout_seconds: float = 30.0
    gemini_temperature: float = 0.2
    gemini_max_output_tokens: int = 512
    embedding_dimension: int = 768
    embedding_batch_size: int = 20

    # --- Database ---
    # Local development default only. Production must supply DATABASE_URL.
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/document_qa"
    database_echo: bool = False

    # --- Authentication ---
    jwt_secret_key: str | None = None
    jwt_algorithm: str = "HS256"
    access_token_expire_seconds: int = 3600

    # --- Ingestion / retrieval ---
    max_upload_size_bytes: int = 10 * 1024 * 1024
    rag_default_top_k: int = 3
    rag_max_top_k: int = 10
    rag_min_similarity: float = 0.5

    # --- S3 (private storage for the original PDF) ---
    # A bucket name enables S3 storage, at which point the region is required.
    # The static credentials are optional: when they are unset boto3 falls back
    # to its normal provider chain (environment, shared config, IAM role), so
    # the application can run on an instance role without secrets on disk.
    aws_region: str | None = None
    s3_bucket_name: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() in {"production", "prod"}

    @property
    def s3_enabled(self) -> bool:
        """S3 storage is active once a bucket name is configured."""

        return bool(self.s3_bucket_name and self.s3_bucket_name.strip())


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings instance."""

    return Settings()


def validate_startup_settings(settings: Settings | None = None) -> None:
    """Fail fast when the application is started with unsafe configuration.

    Raises ``RuntimeError`` instead of silently falling back to a weak or
    guessable signing key, or to a half-configured S3 target.
    """

    settings = settings or get_settings()

    if not settings.jwt_secret_key:
        raise RuntimeError(
            "JWT_SECRET_KEY is not set. Add it to your environment or .env file. "
            'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(48))"'
        )

    if settings.gemini_api_key and settings.jwt_secret_key == settings.gemini_api_key:
        raise RuntimeError(
            "JWT_SECRET_KEY must not reuse GEMINI_API_KEY. Use a dedicated signing secret."
        )

    if len(settings.jwt_secret_key) < MIN_JWT_SECRET_LENGTH:
        raise RuntimeError(
            f"JWT_SECRET_KEY must be at least {MIN_JWT_SECRET_LENGTH} characters long."
        )

    if not settings.gemini_api_key:
        logger.warning(
            "GEMINI_API_KEY is not configured. Embedding and answer endpoints will "
            "return an error until it is set."
        )

    # S3 is half-configured: a bucket with no region cannot be addressed safely,
    # so refuse to start rather than guess an endpoint. Credentials are not
    # checked here - boto3 resolves them through its own provider chain.
    if settings.s3_enabled and not settings.aws_region:
        raise RuntimeError(
            "AWS_REGION is required when S3_BUCKET_NAME is set. Set AWS_REGION to "
            "the region the bucket lives in (for example eu-west-1)."
        )

    if not settings.s3_enabled:
        logger.warning(
            "S3_BUCKET_NAME is not configured. Original PDFs cannot be stored, so "
            "document uploads will be rejected until it is set."
        )
