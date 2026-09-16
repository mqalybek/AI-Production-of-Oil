"""Настройки приложения, читаются из переменных окружения / .env."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+psycopg://monitoring:monitoring@localhost:5432/production_monitoring"
    )


settings = Settings()
