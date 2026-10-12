"""Этап 3: движок магазинов — маршрутизация по shop_id, изоляция, /start, синхронизация."""
import pytest
from aiogram import Bot
from aiogram.methods import SendMessage

from app.security.webhook import shop_webhook_secret
from app.services.shops import ShopService
from app.shops.engine import ShopEngine
from app.telegram.gateway import TelegramUnavailable
from tests.conftest import BUILDER_BOT_ID, TOKEN_A, TOKEN_B
from tests.tg_fakes import RecordingSession, text_update

PUBLIC = "https://x.example"
MASTER = "master"


class BotFactory:
    """Создаёт Bot с записывающей сессией; сессии доступны по токену."""

    def __init__(self) -> None:
        self.sessions: dict[str, RecordingSession] = {}
        self.created = 0

    def __call__(self, token: str) -> Bot:
        self.created += 1
        self.sessions[token] = RecordingSession()
        return Bot(token, session=self.sessions[token])


@pytest.fixture
def env(sessionmaker, cipher, gateway):
    gateway.register(TOKEN_A, "a_bot")
    gateway.register(TOKEN_B, "b_bot")
    service = ShopService(sessionmaker, cipher, gateway, public_url=PUBLIC,
                          webhook_master_secret=MASTER, builder_bot_id=BUILDER_BOT_ID)
    factory = BotFactory()
    engine = ShopEngine(sessionmaker, cipher, gateway, public_url=PUBLIC,
                        webhook_master_secret=MASTER, bot_factory=factory)
    service.on_deactivated = engine.shop_deactivated
    return service, engine, factory, gateway


def payload(uid: int, text: str) -> dict:
    return text_update(uid, text).model_dump(mode="json", exclude_none=True)


def web_app_url(req: SendMessage) -> str:
    return req.reply_markup.inline_keyboard[0][0].web_app.url


# ── /start и маршрутизация ──

async def test_start_in_shop_bot(env):
    service, engine, factory, _ = env
    shop = await service.create_shop(owner_id=1, token=TOKEN_A, admin_id=500, name="Чайная <лавка>")

    assert await engine.feed_webhook(shop.id, payload(42, "/start")) is True
    [reply] = factory.sessions[TOKEN_A].sent()
    assert "Добро пожаловать в <b>Чайная &lt;лавка&gt;</b>" in reply.text
    assert "администратор" not in reply.text.lower()  # покупателю — без админской приписки
    assert web_app_url(reply) == f"{PUBLIC}/?shop={shop.id}"
    assert reply.reply_markup.inline_keyboard[0][0].text == "Open"


async def test_admin_sees_admin_note(env):
    service, engine, factory, _ = env
    shop = await service.create_shop(owner_id=1, token=TOKEN_A, admin_id=500, name="A")
    await engine.feed_webhook(shop.id, payload(500, "/start"))
    assert "Вы главный администратор" in factory.sessions[TOKEN_A].texts()[-1]


async def test_admin_change_applies_immediately(env):
    service, engine, factory, _ = env
    shop = await service.create_shop(owner_id=1, token=TOKEN_A, admin_id=500, name="A")
    await service.change_admin(1, shop.id, 777)
    await engine.feed_webhook(shop.id, payload(500, "/start"))
    await engine.feed_webhook(shop.id, payload(777, "/start"))
    old_admin, new_admin = factory.sessions[TOKEN_A].texts()
    assert "администратор" not in old_admin and "Вы главный администратор" in new_admin


async def test_any_message_gets_shop_button(env):
    service, engine, factory, _ = env
    shop = await service.create_shop(owner_id=1, token=TOKEN_A, admin_id=500, name="A")
    await engine.feed_webhook(shop.id, payload(42, "сколько стоит доставка?"))
    [reply] = factory.sessions[TOKEN_A].sent()
    assert web_app_url(reply) == f"{PUBLIC}/?shop={shop.id}"


async def test_updates_routed_to_own_bot_only(env):
    service, engine, factory, _ = env
    a = await service.create_shop(owner_id=1, token=TOKEN_A, admin_id=1, name="A")
    b = await service.create_shop(owner_id=2, token=TOKEN_B, admin_id=2, name="B")

    await engine.feed_webhook(b.id, payload(42, "/start"))
    assert TOKEN_A not in factory.sessions  # бот магазина A даже не создавался
    [reply] = factory.sessions[TOKEN_B].sent()
    assert "<b>B</b>" in reply.text and web_app_url(reply).endswith(f"?shop={b.id}")

    await engine.feed_webhook(a.id, payload(42, "/start"))
    assert len(factory.sessions[TOKEN_B].sent()) == 1  # B не получил чужой апдейт
    assert "<b>A</b>" in factory.sessions[TOKEN_A].texts()[0]


async def test_bot_instances_are_cached(env):
    service, engine, factory, _ = env
    shop = await service.create_shop(owner_id=1, token=TOKEN_A, admin_id=1, name="A")
    for _ in range(3):
        await engine.feed_webhook(shop.id, payload(42, "/start"))
    assert factory.created == 1
    assert len(factory.sessions[TOKEN_A].sent()) == 3


# ── выключенные и несуществующие магазины ──

async def test_disabled_shop_is_silent_and_bot_released(env):
    service, engine, factory, _ = env
    shop = await service.create_shop(owner_id=1, token=TOKEN_A, admin_id=1, name="A")
    await engine.feed_webhook(shop.id, payload(42, "/start"))
    session = factory.sessions[TOKEN_A]

    await service.set_active(1, shop.id, False)
    assert getattr(session, "closed", False)  # сессия бота закрыта
    session.reset()
    assert await engine.feed_webhook(shop.id, payload(42, "/start")) is False
    assert session.sent() == []

    await service.set_active(1, shop.id, True)
    assert await engine.feed_webhook(shop.id, payload(42, "/start")) is True
    assert factory.sessions[TOKEN_A].sent()  # новый экземпляр бота снова отвечает


async def test_unknown_shop_dropped(env):
    _, engine, factory, _ = env
    assert await engine.feed_webhook(999, payload(42, "/start")) is False
    assert factory.created == 0


# ── секреты вебхука ──

async def test_webhook_secret_is_per_shop(env):
    _, engine, _, _ = env
    assert engine.verify_secret(1, shop_webhook_secret(MASTER, 1))
    assert not engine.verify_secret(2, shop_webhook_secret(MASTER, 1))  # секрет A в URL магазина B
    assert not engine.verify_secret(1, None)
    assert not engine.verify_secret(1, shop_webhook_secret("other-master", 1))


# ── синхронизация при старте ──

async def test_sync_all_configures_active_shops_without_dropping_updates(env):
    service, engine, _, gateway = env
    a = await service.create_shop(owner_id=1, token=TOKEN_A, admin_id=1, name="A")
    b = await service.create_shop(owner_id=1, token=TOKEN_B, admin_id=1, name="B")
    await service.set_active(1, b.id, False)
    gateway.calls.clear()

    report = await engine.sync_all()
    assert report.ok == [a.id] and report.failed == []
    [call] = [c for c in gateway.calls if c[0] == "configure"]
    assert call[1] == TOKEN_A and call[2] == f"{PUBLIC}/webhook/{a.id}"
    assert gateway.configure_kwargs[-1]["drop_pending_updates"] is False


async def test_sync_all_survives_broken_shop(env):
    service, engine, _, gateway = env
    a = await service.create_shop(owner_id=1, token=TOKEN_A, admin_id=1, name="A")
    b = await service.create_shop(owner_id=1, token=TOKEN_B, admin_id=1, name="B")

    original = gateway.configure_shop_bot

    async def flaky(token, **kw):
        if token == TOKEN_A:
            raise TelegramUnavailable()
        return await original(token, **kw)

    gateway.configure_shop_bot = flaky
    report = await engine.sync_all()
    assert report.failed == [a.id] and report.ok == [b.id]


async def test_shop_created_then_engine_serves_it_without_restart(env):
    # Магазин, созданный в конструкторе, отвечает сразу — без перезапуска сервиса
    service, engine, factory, _ = env
    await engine.sync_all()  # «старт сервиса» — магазинов ещё нет
    shop = await service.create_shop(owner_id=1, token=TOKEN_A, admin_id=1, name="A")
    assert await engine.feed_webhook(shop.id, payload(42, "/start")) is True
    assert factory.sessions[TOKEN_A].sent()


# ── приглашения в админы через /start adm_<token> (этап 6.5) ──

from datetime import datetime, timedelta, timezone  # noqa: E402

from sqlalchemy import update  # noqa: E402

from app.db.models import AdminInvite  # noqa: E402
from app.services import admins as admin_svc  # noqa: E402


async def make_invite(sessionmaker, shop_id: int) -> str:
    from app.db.models import Shop
    async with sessionmaker() as s:
        link, _ = await admin_svc.create_invite(s, await s.get(Shop, shop_id), created_by=500)
    return link.split("?start=")[1]


async def test_invite_accepted_once(env, sessionmaker):
    service, engine, factory, _ = env
    shop = await service.create_shop(owner_id=1, token=TOKEN_A, admin_id=500, name="A")
    param = await make_invite(sessionmaker, shop.id)

    await engine.feed_webhook(shop.id, payload(600, f"/start {param}"))
    sent = factory.sessions[TOKEN_A].sent()
    assert "Вы стали администратором" in sent[0].text
    assert sent[1].chat_id == 500 and "стал администратором" in sent[1].text  # главному — уведомление

    await engine.feed_webhook(shop.id, payload(600, "/start"))
    assert "Вы администратор этого магазина" in factory.sessions[TOKEN_A].texts()[-1]

    # повторное использование той же ссылки другим человеком — отказ
    await engine.feed_webhook(shop.id, payload(601, f"/start {param}"))
    assert "недействительна" in factory.sessions[TOKEN_A].texts()[-1]
    async with sessionmaker() as s:
        from app.db.models import Shop
        roles = await admin_svc.load_roles(s, await s.get(Shop, shop.id))
    assert roles.extra_admin_ids == {600}


async def test_invite_expired_or_forged(env, sessionmaker):
    service, engine, factory, _ = env
    shop = await service.create_shop(owner_id=1, token=TOKEN_A, admin_id=500, name="A")
    param = await make_invite(sessionmaker, shop.id)
    async with sessionmaker() as s:
        await s.execute(update(AdminInvite).values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
        await s.commit()
    await engine.feed_webhook(shop.id, payload(600, f"/start {param}"))
    await engine.feed_webhook(shop.id, payload(600, "/start adm_forgedtoken123456789"))
    texts = factory.sessions[TOKEN_A].texts()
    assert all("недействительна" in t for t in texts)


async def test_invite_from_previous_main_admin_is_void(env, sessionmaker):
    service, engine, factory, _ = env
    shop = await service.create_shop(owner_id=1, token=TOKEN_A, admin_id=500, name="A")
    param = await make_invite(sessionmaker, shop.id)
    await service.change_admin(1, shop.id, 700)  # владелец сменил главного админа
    await engine.feed_webhook(shop.id, payload(600, f"/start {param}"))
    assert "больше не действует" in factory.sessions[TOKEN_A].texts()[-1]


async def test_invite_for_another_shop_does_not_work(env, sessionmaker):
    service, engine, factory, _ = env
    a = await service.create_shop(owner_id=1, token=TOKEN_A, admin_id=500, name="A")
    b = await service.create_shop(owner_id=1, token=TOKEN_B, admin_id=500, name="B")
    param = await make_invite(sessionmaker, a.id)
    await engine.feed_webhook(b.id, payload(600, f"/start {param}"))
    assert "недействительна" in factory.sessions[TOKEN_B].texts()[-1]


async def test_new_main_admin_removed_from_extra_list(env, sessionmaker):
    service, engine, factory, _ = env
    shop = await service.create_shop(owner_id=1, token=TOKEN_A, admin_id=500, name="A")
    param = await make_invite(sessionmaker, shop.id)
    await engine.feed_webhook(shop.id, payload(600, f"/start {param}"))
    await service.change_admin(1, shop.id, 600)
    from app.db.models import Shop
    async with sessionmaker() as s:
        roles = await admin_svc.load_roles(s, await s.get(Shop, shop.id))
    assert roles.main_admin_id == 600 and roles.extra_admin_ids == frozenset()
