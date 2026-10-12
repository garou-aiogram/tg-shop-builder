"""Секреты вебхуков.

Telegram присылает заголовок X-Telegram-Bot-Api-Secret-Token со значением,
заданным в setWebhook. Секрет каждого бота выводится из WEBHOOK_SECRET через
HMAC — хранить его в БД не нужно, а утечка секрета одного магазина не даёт
подделывать запросы к другим.
"""
import hashlib
import hmac


def derive_secret(master: str, purpose: str) -> str:
    # hex: только [0-9a-f] — разрешённый Telegram алфавит; 64 символа ≤ лимита 256
    return hmac.new(master.encode(), purpose.encode(), hashlib.sha256).hexdigest()


def builder_webhook_secret(master: str) -> str:
    return derive_secret(master, "builder")


def shop_webhook_secret(master: str, shop_id: int) -> str:
    return derive_secret(master, f"shop:{shop_id}")


def secrets_equal(received: str | None, expected: str) -> bool:
    # Сравнение за постоянное время — без утечки по таймингу
    return received is not None and hmac.compare_digest(received.encode(), expected.encode())
