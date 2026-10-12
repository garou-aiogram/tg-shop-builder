"""Конфигурация приложения — только из переменных окружения (.env).

Намеренно без pydantic-settings, чтобы не тянуть зависимость вне стека:
pydantic уже есть (через FastAPI/aiogram), читаем os.environ сами.
"""
from __future__ import annotations

import os
from functools import lru_cache

from pydantic import BaseModel, SecretStr, field_validator


class Settings(BaseModel):
    # Главный бот-конструктор
    builder_bot_token: SecretStr

    # Публичный HTTPS-адрес (nginx фронтенда): статика + /api + /webhook + /media
    public_url: str

    # БД
    database_url: str

    # Ключ Fernet для шифрования токенов ботов магазинов
    fernet_key: SecretStr

    # Секрет для X-Telegram-Bot-Api-Secret-Token (из него выводится секрет каждого вебхука)
    webhook_secret: SecretStr

    media_dir: str = "/app/media"
    log_level: str = "INFO"

    @field_validator("public_url")
    @classmethod
    def _strip_slash(cls, v: str) -> str:
        v = v.rstrip("/")
        if not v.startswith("https://"):
            # Telegram принимает WebApp URL и webhook только по HTTPS
            raise ValueError("PUBLIC_URL должен начинаться с https://")
        return v

    @field_validator("fernet_key")
    @classmethod
    def _valid_fernet(cls, v: SecretStr) -> SecretStr:
        from cryptography.fernet import Fernet

        try:
            Fernet(v.get_secret_value().encode())
        except Exception:
            raise ValueError(
                "FERNET_KEY невалиден. Сгенерируйте: "
                'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
            ) from None
        return v

    @field_validator("database_url")
    @classmethod
    def _async_driver(cls, v: str) -> str:
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL должен использовать драйвер postgresql+asyncpg://")
        return v


_ENV_MAP = {
    "builder_bot_token": "BUILDER_BOT_TOKEN",
    "public_url": "PUBLIC_URL",
    "database_url": "DATABASE_URL",
    "fernet_key": "FERNET_KEY",
    "webhook_secret": "WEBHOOK_SECRET",
    "media_dir": "MEDIA_DIR",
    "log_level": "LOG_LEVEL",
}


def load_settings(env: dict[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    data = {field: env[var] for field, var in _ENV_MAP.items() if var in env}
    return Settings(**data)


@lru_cache
def get_settings() -> Settings:
    return load_settings()
