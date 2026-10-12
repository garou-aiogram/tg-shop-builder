"""Проверка Telegram Mini App initData.

Алгоритм (https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app):
  secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
  hash       = hex(HMAC_SHA256(key=secret_key, msg=data_check_string))
где data_check_string — все поля, кроме hash, в виде "key=value", отсортированные
по ключу и соединённые "\\n".

Подпись делается токеном КОНКРЕТНОГО бота, поэтому initData из магазина A
не пройдёт проверку в магазине B — изоляция арендаторов на уровне криптографии.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

DEFAULT_MAX_AGE = 24 * 3600  # initData выдаётся при открытии Mini App; сутки — с запасом


class InitDataError(Exception):
    pass


@dataclass(frozen=True)
class WebAppUser:
    id: int
    first_name: str
    last_name: str | None = None
    username: str | None = None


def _secret_key(bot_token: str) -> bytes:
    return hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()


def sign_init_data(fields: dict[str, str], bot_token: str) -> str:
    """Подписать поля так же, как Telegram. Используется в тестах и для локальной отладки."""
    from urllib.parse import urlencode

    dcs = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    h = hmac.new(_secret_key(bot_token), dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": h})


def validate_init_data(
    init_data: str, bot_token: str, *, max_age: int = DEFAULT_MAX_AGE, now: float | None = None
) -> WebAppUser:
    if not init_data:
        raise InitDataError("empty initData")
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    except ValueError as e:
        raise InitDataError("malformed initData") from e

    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise InitDataError("duplicate keys")  # защита от подмены через повтор параметра
    received_hash = fields.pop("hash", None)
    if not received_hash:
        raise InitDataError("no hash")

    dcs = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    expected = hmac.new(_secret_key(bot_token), dcs.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        raise InitDataError("bad signature")

    try:
        auth_date = int(fields["auth_date"])
    except (KeyError, ValueError) as e:
        raise InitDataError("no auth_date") from e
    now = time.time() if now is None else now
    if now - auth_date > max_age:
        raise InitDataError("initData expired")
    if auth_date - now > 60:
        raise InitDataError("auth_date in the future")

    try:
        user = json.loads(fields["user"])
        return WebAppUser(
            id=int(user["id"]),
            first_name=str(user.get("first_name", "")),
            last_name=user.get("last_name"),
            username=user.get("username"),
        )
    except (KeyError, ValueError, TypeError) as e:
        raise InitDataError("no user") from e
