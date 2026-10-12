"""Тесты с БД идут против настоящего PostgreSQL (TEST_DATABASE_URL).
Схема создаётся через Alembic-миграции — так тесты заодно проверяют миграции.
ВНИМАНИЕ: тестовая БД полностью очищается, не указывайте рабочую."""
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.session import make_sessionmaker

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
BACKEND_DIR = os.path.dirname(os.path.dirname(__file__))


def alembic_cfg() -> Config:
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.attributes["database_url"] = TEST_DB_URL
    return cfg


@pytest.fixture(scope="session")
def migrated_db():
    if not TEST_DB_URL:
        pytest.skip("TEST_DATABASE_URL не задан")
    cfg = alembic_cfg()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield
    command.downgrade(cfg, "base")


@pytest.fixture(scope="session")
async def engine(migrated_db):
    eng = create_async_engine(TEST_DB_URL)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine):
    """Каждый тест — в транзакции, которая в конце откатывается."""
    async with engine.connect() as conn:
        trans = await conn.begin()
        maker = make_sessionmaker(conn)  # type: ignore[arg-type]
        async with maker(join_transaction_mode="create_savepoint") as s:
            yield s
        await trans.rollback()


# ─── Общие фикстуры этапа 2 ─────────────────────────────────────────────

from cryptography.fernet import Fernet
from sqlalchemy import text

from app.security.crypto import TokenCipher
from app.telegram.gateway import BotIdentity, TokenRejected


@pytest.fixture
async def sessionmaker(engine):
    """Сессии, которые коммитят по-настоящему (как в сервисе). После теста — чистка."""
    yield make_sessionmaker(engine)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE shops RESTART IDENTITY CASCADE"))


@pytest.fixture
def cipher() -> TokenCipher:
    return TokenCipher(Fernet.generate_key().decode())


class FakeGateway:
    """Подмена Telegram: помнит вызовы, умеет падать по заказу."""

    def __init__(self) -> None:
        self.bots: dict[str, BotIdentity] = {}
        self.calls: list[tuple] = []
        self.fail_configure: Exception | None = None
        self.fail_get_me: Exception | None = None
        self.configure_kwargs: list[dict] = []

    def register(self, token: str, username: str) -> str:
        self.bots[token] = BotIdentity(id=int(token.split(":")[0]), username=username, first_name=username)
        return token

    async def get_me(self, token: str) -> BotIdentity:
        self.calls.append(("get_me", token))
        if self.fail_get_me:
            raise self.fail_get_me
        if token not in self.bots:
            raise TokenRejected()
        return self.bots[token]

    async def configure_shop_bot(self, token, *, webhook_url, secret, webapp_url, drop_pending_updates=True) -> None:
        self.calls.append(("configure", token, webhook_url, secret, webapp_url))
        self.configure_kwargs.append({"drop_pending_updates": drop_pending_updates})
        if self.fail_configure:
            raise self.fail_configure

    async def disable_shop_bot(self, token) -> None:
        self.calls.append(("disable", token))


@pytest.fixture
def gateway() -> FakeGateway:
    return FakeGateway()


BUILDER_BOT_ID = 999_000_001
TOKEN_A = "111111111:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
TOKEN_B = "222222222:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
BUILDER_TOKEN = f"{BUILDER_BOT_ID}:CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC"
