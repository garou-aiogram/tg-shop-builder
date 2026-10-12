"""Этап 2: создание магазина и управление им (Telegram подменён FakeGateway)."""
import pytest
from sqlalchemy import func, select

from app.db.models import Shop
from app.security.webhook import shop_webhook_secret
from app.services.shops import (
    BotAlreadyUsed,
    BuilderTokenUsed,
    InvalidInput,
    InvalidToken,
    ShopNotFound,
    ShopService,
    TelegramFailed,
    parse_telegram_id,
    validate_shop_name,
    validate_token_format,
)
from app.telegram.gateway import TelegramUnavailable, TokenRejected
from tests.conftest import BUILDER_BOT_ID, BUILDER_TOKEN, TOKEN_A, TOKEN_B

PUBLIC = "https://shop.example.com"
MASTER = "master-secret"


@pytest.fixture
def service(sessionmaker, cipher, gateway) -> ShopService:
    gateway.register(TOKEN_A, "shop_a_bot")
    gateway.register(TOKEN_B, "shop_b_bot")
    return ShopService(sessionmaker, cipher, gateway, public_url=PUBLIC,
                       webhook_master_secret=MASTER, builder_bot_id=BUILDER_BOT_ID)


async def count_shops(sessionmaker) -> int:
    async with sessionmaker() as s:
        return await s.scalar(select(func.count(Shop.id)))


# ── валидаторы ──

@pytest.mark.parametrize("raw", ["", "abc", "123:short", "12:" + "A" * 35, TOKEN_A + " extra"])
def test_bad_token_format(raw):
    with pytest.raises(InvalidInput):
        validate_token_format(raw)


def test_token_format_strips_spaces():
    assert validate_token_format(f"  {TOKEN_A}\n") == TOKEN_A


@pytest.mark.parametrize("raw,expected", [("123456789", 123456789), (" 42 ", 42)])
def test_parse_telegram_id_ok(raw, expected):
    assert parse_telegram_id(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "-5", "0", "12.5", "9" * 30, "@username"])
def test_parse_telegram_id_bad(raw):
    with pytest.raises(InvalidInput):
        parse_telegram_id(raw)


def test_shop_name_normalized_and_limited():
    assert validate_shop_name("  Мой   магазин\n ") == "Мой магазин"
    with pytest.raises(InvalidInput):
        validate_shop_name("   ")
    with pytest.raises(InvalidInput):
        validate_shop_name("x" * 65)


# ── создание ──

async def test_create_shop_happy_path(service, sessionmaker, cipher, gateway):
    shop = await service.create_shop(owner_id=10, token=TOKEN_A, admin_id=20, name="Чай")

    async with sessionmaker() as s:
        db_shop = await s.get(Shop, shop.id)
    assert db_shop.owner_id == 10 and db_shop.admin_id == 20 and db_shop.is_active
    assert db_shop.bot_id == 111111111 and db_shop.bot_username == "shop_a_bot"
    # в БД — только шифротекст, и он расшифровывается в исходный токен
    assert TOKEN_A not in db_shop.bot_token_encrypted
    assert cipher.decrypt(db_shop.bot_token_encrypted) == TOKEN_A

    configure = [c for c in gateway.calls if c[0] == "configure"]
    assert configure == [(
        "configure", TOKEN_A,
        f"{PUBLIC}/webhook/{shop.id}",
        shop_webhook_secret(MASTER, shop.id),
        f"{PUBLIC}/?shop={shop.id}",
    )]


async def test_duplicate_bot_rejected(service, sessionmaker):
    await service.create_shop(owner_id=10, token=TOKEN_A, admin_id=20, name="A")
    with pytest.raises(BotAlreadyUsed):
        await service.check_token(TOKEN_A)
    with pytest.raises(BotAlreadyUsed):
        await service.create_shop(owner_id=11, token=TOKEN_A, admin_id=21, name="A2")
    assert await count_shops(sessionmaker) == 1


async def test_builder_own_token_rejected(service, gateway):
    gateway.register(BUILDER_TOKEN, "builder_bot")
    with pytest.raises(BuilderTokenUsed):
        await service.check_token(BUILDER_TOKEN)
    assert gateway.calls == []  # отсекли до сетевого вызова


async def test_unknown_token_rejected(service, sessionmaker):
    with pytest.raises(InvalidToken):
        await service.create_shop(owner_id=1, token="333333333:" + "Z" * 35, admin_id=1, name="X")
    assert await count_shops(sessionmaker) == 0


async def test_telegram_down_on_get_me(service, gateway):
    gateway.fail_get_me = TelegramUnavailable()
    with pytest.raises(TelegramFailed):
        await service.check_token(TOKEN_A)


@pytest.mark.parametrize("error,expected", [(TelegramUnavailable(), TelegramFailed), (TokenRejected(), InvalidToken)])
async def test_setup_failure_rolls_back(service, sessionmaker, gateway, error, expected):
    gateway.fail_configure = error
    with pytest.raises(expected):
        await service.create_shop(owner_id=1, token=TOKEN_A, admin_id=1, name="X")
    assert await count_shops(sessionmaker) == 0
    assert ("disable", TOKEN_A) in gateway.calls  # вебхук за собой убрали
    # и тот же бот после сбоя можно подключить заново
    gateway.fail_configure = None
    await service.create_shop(owner_id=1, token=TOKEN_A, admin_id=1, name="X")


# ── управление: только владелец ──

async def test_list_only_own_shops(service):
    await service.create_shop(owner_id=10, token=TOKEN_A, admin_id=1, name="A")
    await service.create_shop(owner_id=77, token=TOKEN_B, admin_id=1, name="B")
    assert [s.name for s in await service.list_shops(10)] == ["A"]
    assert [s.name for s in await service.list_shops(77)] == ["B"]
    assert await service.list_shops(5) == []


async def test_stranger_cannot_manage_shop(service):
    shop = await service.create_shop(owner_id=10, token=TOKEN_A, admin_id=20, name="A")
    # даже администратор магазина — не владелец в конструкторе
    for stranger in (20, 99):
        with pytest.raises(ShopNotFound):
            await service.get_owned_shop(stranger, shop.id)
        with pytest.raises(ShopNotFound):
            await service.set_active(stranger, shop.id, False)
        with pytest.raises(ShopNotFound):
            await service.change_admin(stranger, shop.id, stranger)
    assert (await service.get_owned_shop(10, shop.id)).admin_id == 20


async def test_toggle_shop(service, gateway):
    shop = await service.create_shop(owner_id=10, token=TOKEN_A, admin_id=20, name="A")
    gateway.calls.clear()

    off = await service.set_active(10, shop.id, False)
    assert off.is_active is False and gateway.calls == [("disable", TOKEN_A)]

    gateway.calls.clear()
    on = await service.set_active(10, shop.id, True)
    assert on.is_active is True and gateway.calls[0][:3] == ("configure", TOKEN_A, f"{PUBLIC}/webhook/{shop.id}")

    gateway.calls.clear()
    await service.set_active(10, shop.id, True)  # уже включён — Telegram не дёргаем
    assert gateway.calls == []


async def test_enable_fails_keeps_shop_disabled(service, gateway):
    shop = await service.create_shop(owner_id=10, token=TOKEN_A, admin_id=20, name="A")
    await service.set_active(10, shop.id, False)
    gateway.fail_configure = TokenRejected()  # токен отозвали в BotFather
    with pytest.raises(InvalidToken):
        await service.set_active(10, shop.id, True)
    assert (await service.get_owned_shop(10, shop.id)).is_active is False


async def test_change_admin(service):
    shop = await service.create_shop(owner_id=10, token=TOKEN_A, admin_id=20, name="A")
    await service.change_admin(10, shop.id, 30)
    assert (await service.get_owned_shop(10, shop.id)).admin_id == 30
