"""Этап 2: сквозной сценарий главного бота через диспетчер aiogram.

Сеть не используется: сессия Bot подменена RecordingSession (tests/tg_fakes.py).
"""
import pytest
from aiogram import Bot
from aiogram.methods import AnswerCallbackQuery, DeleteMessage

from app.builder.keyboards import MenuCb, ShopCb
from app.builder.setup import build_builder_dispatcher
from app.services.shops import ShopService
from tests.conftest import BUILDER_BOT_ID, TOKEN_A
from tests.tg_fakes import RecordingSession, callback_update, text_update


class Harness:
    def __init__(self, dp, bot, session) -> None:
        self.dp, self.bot, self.session = dp, bot, session

    async def text(self, uid: int, text: str) -> None:
        await self.dp.feed_update(self.bot, text_update(uid, text))

    async def press(self, uid: int, data) -> None:
        await self.dp.feed_update(self.bot, callback_update(uid, data.pack()))

    async def fsm_data(self, uid: int) -> dict:
        from aiogram.fsm.storage.base import StorageKey
        key = StorageKey(bot_id=self.bot.id, chat_id=uid, user_id=uid)
        return await self.dp.storage.get_data(key)


@pytest.fixture
def harness(sessionmaker, cipher, gateway):
    gateway.register(TOKEN_A, "tea_shop_bot")
    service = ShopService(sessionmaker, cipher, gateway, public_url="https://x.example",
                          webhook_master_secret="m", builder_bot_id=BUILDER_BOT_ID)
    from app.builder import handlers
    handlers.router._parent_router = None  # один router на процесс: отвязываем между тестами
    dp = build_builder_dispatcher(shop_service=service, cipher=cipher)
    session = RecordingSession()
    bot = Bot(f"{BUILDER_BOT_ID}:TESTTESTTESTTESTTESTTESTTESTTESTTEST", session=session)
    return Harness(dp, bot, session), service


async def test_full_create_flow(harness):
    h, service = harness
    owner = 5001

    await h.text(owner, "/start")
    assert "Конструктор магазинов" in h.session.texts()[-1]

    await h.press(owner, MenuCb(action="create"))
    assert "Шаг 1 из 3" in h.session.texts()[-1]

    h.session.reset()
    await h.text(owner, TOKEN_A)
    # сообщение с токеном удалено из чата
    assert any(isinstance(r, DeleteMessage) for r in h.session.requests)
    assert "@tea_shop_bot найден" in h.session.texts()[-1]
    # в FSM-хранилище токена в открытом виде нет
    data = await h.fsm_data(owner)
    assert TOKEN_A not in str(data) and "token_enc" in data
    # и сам токен бот нигде не повторил
    assert all(TOKEN_A not in t for t in h.session.texts())

    await h.text(owner, "not-a-number")
    assert "ID — это число" in h.session.texts()[-1]

    await h.press(owner, MenuCb(action="admin_me"))
    assert "Шаг 3 из 3" in h.session.texts()[-1]

    h.session.reset()
    await h.text(owner, "<b>Чайная</b> лавка")
    assert "создан" in h.session.texts()[-1]
    # «⏳ Создаю магазин…» не остался в чате: его заменили результатом
    from aiogram.methods import EditMessageText
    assert isinstance(h.session.sent()[-1], EditMessageText)
    assert len([t for t in h.session.texts() if t.startswith("⏳")]) == 1
    # HTML в названии экранирован
    assert "&lt;b&gt;Чайная&lt;/b&gt;" in h.session.texts()[-1]

    shops = await service.list_shops(owner)
    assert len(shops) == 1 and shops[0].admin_id == owner and shops[0].name == "<b>Чайная</b> лавка"
    assert await h.fsm_data(owner) == {}


async def test_invalid_token_keeps_step(harness):
    h, service = harness
    await h.press(6001, MenuCb(action="create"))
    await h.text(6001, "hello")
    assert "не похоже на токен" in h.session.texts()[-1]
    await h.text(6001, "444444444:" + "Q" * 35)  # формат верный, но Telegram его не знает
    assert "Telegram не принял" in h.session.texts()[-1]
    assert await service.list_shops(6001) == []


async def test_cancel_clears_state(harness):
    h, _ = harness
    await h.press(7001, MenuCb(action="create"))
    await h.press(7001, MenuCb(action="cancel"))
    assert await h.fsm_data(7001) == {}
    await h.text(7001, TOKEN_A)  # после отмены токен — просто текст, магазин не создаётся
    assert "Конструктор магазинов" in h.session.texts()[-1]


async def test_forged_callback_for_foreign_shop(harness):
    h, service = harness
    shop = await service.create_shop(owner_id=8001, token=TOKEN_A, admin_id=8001, name="A")
    h.session.reset()
    # чужой пользователь подделывает callback_data «выключить магазин #N»
    await h.press(8002, ShopCb(action="off", shop_id=shop.id))
    alerts = [r for r in h.session.requests if isinstance(r, AnswerCallbackQuery)]
    assert alerts and alerts[-1].text == "Магазин не найден." and alerts[-1].show_alert
    assert (await service.get_owned_shop(8001, shop.id)).is_active is True


async def test_owner_toggles_and_changes_admin(harness):
    h, service = harness
    shop = await service.create_shop(owner_id=9001, token=TOKEN_A, admin_id=9001, name="A")
    await h.press(9001, ShopCb(action="off", shop_id=shop.id))
    assert (await service.get_owned_shop(9001, shop.id)).is_active is False

    await h.press(9001, ShopCb(action="admin", shop_id=shop.id))
    await h.text(9001, "123456")
    assert "Администратор изменён" in h.session.texts()[-1]
    assert (await service.get_owned_shop(9001, shop.id)).admin_id == 123456
