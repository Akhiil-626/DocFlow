from decimal import Decimal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ENVIRONMENT: str = "development"
    DATABASE_URL: str = "postgresql+psycopg://docflow:docflow_password@localhost:5432/docflow"
    DB_USER: str = "docflow"
    DB_PASSWORD: str = "docflow_password"
    DB_NAME: str = "docflow"

    JWT_SECRET: str = "supersecretjwtkeythatisatleast32characterslongforsecurity"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    UPLOAD_DIR: str = "./uploads"
    MAX_FILE_SIZE_BYTES: int = 10 * 1024 * 1024  # 10 MB

    # Redis and Celery settings
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    # Validation Settings & Thresholds
    VALIDATION_TOLERANCE: Decimal = Decimal("1.00")
    VALIDATION_MAX_INVOICE_AGE_DAYS: int = 365
    VALIDATION_ALLOWED_TAX_RATES: list[Decimal] = [
        Decimal("0.00"),
        Decimal("0.05"),
        Decimal("0.12"),
        Decimal("0.18"),
        Decimal("0.28"),
    ]
    VALIDATION_ALLOWED_GST_STATE_CODES: list[str] = [
        f"{i:02d}" for i in range(1, 38)
    ] + ["38", "97", "99"]
    VALIDATION_WARNINGS_ROUTE_TO_REVIEW: bool = True

    # LLM Settings
    LLM_PROVIDER: str = "mock"  # "mock" or "gemini" or "ollama"
    LLM_API_KEY: str | None = None
    LLM_MODEL: str = "gemini-2.5-flash"
    OLLAMA_BASE_URL: str = "http://host.docker.internal:11434"
    OLLAMA_TIMEOUT_SECONDS: float = 180.0
    OLLAMA_NUM_CTX: int = 8192

    # CORS Settings (explicit list, never wildcard with credentials)
    CORS_ORIGINS: str = "http://localhost:5173"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
