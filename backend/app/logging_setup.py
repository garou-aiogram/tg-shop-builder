"""Логирование: токены ботов вырезаются из ЛЮБОЙ строки лога, включая трейсбеки.

Фильтр стоит на уровне форматтера, поэтому он ловит и то, что пишут сторонние
библиотеки (aiogram/aiohttp могут включить URL с токеном в текст исключения).
"""
import logging
import re

TOKEN_RE = re.compile(r"\d{5,}:[A-Za-z0-9_-]{30,}")
REDACTED = "<bot-token>"


def redact(text: str) -> str:
    return TOKEN_RE.sub(REDACTED, text)


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


class SkipHealthcheck(logging.Filter):
    """Docker дёргает /api/health каждые 5 секунд — не засоряем access-лог."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "/api/health" not in str(record.args)


FORMAT = "%(asctime)s %(levelname)-5s [%(name)s] %(message)s"


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        root.addHandler(logging.StreamHandler())
    formatter = RedactingFormatter(FORMAT)
    # uvicorn настраивает свои логгеры раньше, чем загружается приложение —
    # подменяем форматтер и у них
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
        for handler in logging.getLogger(name).handlers:
            handler.setFormatter(formatter)
    logging.getLogger("uvicorn.access").addFilter(SkipHealthcheck())
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
