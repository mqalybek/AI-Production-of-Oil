"""Настройки приложения, читаются из переменных окружения / .env."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+psycopg://monitoring:monitoring@localhost:5432/production_monitoring"
    )

    # JWT-аутентификация API (src/api/security.py). secret_key — заглушка для
    # разработки, в проде обязательно переопределяется через .env.
    jwt_secret_key: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 480

    # TTL in-memory кэша тяжёлых агрегатов (src/api/cache.py). Без Redis —
    # проект работает on-premise в один процесс uvicorn.
    cache_ttl_seconds: int = 120


settings = Settings()
