"""FastAPI-приложение: API + приём вебхуков. Боты живут в этом же процессе."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, Update
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.staticfiles import StaticFiles

from app.api import admin as admin_api
from app.api import public as public_api
from app.builder.setup import build_builder_dispatcher
from app.config import Settings, get_settings
from app.db.session import make_engine, make_sessionmaker
from app.logging_setup import setup_logging
from app.security.crypto import TokenCipher
from app.security.webhook import builder_webhook_secret, secrets_equal
from app.services.media import MediaStorage
from app.services.shops import ShopService
from app.shops.engine import ShopEngine
from app.telegram.gateway import AiogramBotGateway

log = logging.getLogger("app")

BUILDER_WEBHOOK_PATH = "/webhook/builder"


def _log_task_failure(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception() is not None:
        log.error("background task failed", exc_info=task.exception())


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        cfg = settings or get_settings()
        setup_logging(cfg.log_level)

        engine = make_engine(cfg.database_url)
        sessionmaker = make_sessionmaker(engine)
        cipher = TokenCipher(cfg.fernet_key.get_secret_value())
        master_secret = cfg.webhook_secret.get_secret_value()

        builder_bot = Bot(
            cfg.builder_bot_token.get_secret_value(),
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        try:
            me = await builder_bot.get_me()  # неверный BUILDER_BOT_TOKEN → падаем сразу и явно
        except Exception:
            await builder_bot.session.close()
            await engine.dispose()
            raise

        shop_service = ShopService(
            sessionmaker,
            cipher,
            AiogramBotGateway(),
            public_url=cfg.public_url,
            webhook_master_secret=master_secret,
            builder_bot_id=me.id,
        )
        dp = build_builder_dispatcher(shop_service=shop_service, cipher=cipher)

        engine_shops = ShopEngine(
            sessionmaker,
            cipher,
            AiogramBotGateway(),
            public_url=cfg.public_url,
            webhook_master_secret=master_secret,
        )
        shop_service.on_deactivated = engine_shops.shop_deactivated

        app.state.builder_bot = builder_bot
        app.state.builder_dp = dp
        app.state.builder_secret = builder_webhook_secret(master_secret)
        app.state.sessionmaker = sessionmaker
        app.state.shop_service = shop_service
        app.state.shop_engine = engine_shops
        app.state.cipher = cipher
        app.state.media = MediaStorage(cfg.media_dir)
        os.makedirs(cfg.media_dir, exist_ok=True)

        try:
            await builder_bot.set_webhook(
                url=f"{cfg.public_url}{BUILDER_WEBHOOK_PATH}",
                secret_token=app.state.builder_secret,
                allowed_updates=dp.resolve_used_update_types(),
            )
            await builder_bot.set_my_commands([BotCommand(command="start", description="Главное меню")])
            log.info("builder bot @%s: webhook set to %s%s", me.username, cfg.public_url, BUILDER_WEBHOOK_PATH)
        except Exception as e:  # noqa: BLE001 — API должен подняться, даже если Telegram недоступен
            log.error("builder bot: failed to set webhook (%s). Is PUBLIC_URL reachable over HTTPS?", type(e).__name__)

        # Поднимаем все активные магазины в фоне: API и вебхуки работают сразу
        # (боты создаются лениво), а перенастройка N ботов в Telegram не держит старт.
        sync_task = asyncio.create_task(engine_shops.sync_all())
        sync_task.add_done_callback(_log_task_failure)

        yield

        sync_task.cancel()
        await engine_shops.close()
        await builder_bot.session.close()
        await engine.dispose()

    app = FastAPI(title="TG Shop Builder", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    app.include_router(public_api.router)
    app.include_router(admin_api.router)

    # Фото товаров. nginx проксирует /media/ сюда; имена файлов генерирует сервер.
    # check_dir=False: каталог создаётся в lifespan (при импорте настроек ещё может не быть)
    media_dir = settings.media_dir if settings else os.environ.get("MEDIA_DIR", "/app/media")
    app.mount("/media", StaticFiles(directory=media_dir, check_dir=False), name="media")

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post(BUILDER_WEBHOOK_PATH, include_in_schema=False)
    async def builder_webhook(
        request: Request,
        x_telegram_bot_api_secret_token: str | None = Header(default=None),
    ) -> dict[str, bool]:
        if not secrets_equal(x_telegram_bot_api_secret_token, request.app.state.builder_secret):
            raise HTTPException(status_code=401)
        bot: Bot = request.app.state.builder_bot
        update = Update.model_validate(await request.json(), context={"bot": bot})
        await request.app.state.builder_dp.feed_update(bot, update)
        return {"ok": True}

    @app.post("/webhook/{shop_id}", include_in_schema=False)
    async def shop_webhook(
        shop_id: int,
        request: Request,
        x_telegram_bot_api_secret_token: str | None = Header(default=None),
    ) -> dict[str, bool]:
        engine_shops: ShopEngine = request.app.state.shop_engine
        # Секрет свой у каждого магазина: запрос с секретом магазина A в URL магазина B не пройдёт
        if not engine_shops.verify_secret(shop_id, x_telegram_bot_api_secret_token):
            raise HTTPException(status_code=401)
        # Выключенный/удалённый магазин → 200 без обработки: иначе Telegram будет ретраить
        await engine_shops.feed_webhook(shop_id, await request.json())
        return {"ok": True}

    return app


app = create_app()
