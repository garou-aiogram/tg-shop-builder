"""Движок магазинов: N ботов в одном процессе.

- Один Dispatcher на все магазины; апдейт маршрутизируется по shop_id из URL вебхука.
- Экземпляры Bot кешируются (у каждого своя HTTP-сессия) и создаются лениво
  при первом апдейте — запросы обслуживаются, даже пока идёт стартовая синхронизация.
- Статус магазина читается из БД на каждый апдейт: выключенный магазин
  перестаёт отвечать сразу, даже если Telegram успел прислать апдейт.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Update
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Shop
from app.security.crypto import TokenCipher, TokenDecryptError
from app.security.webhook import secrets_equal, shop_webhook_secret
from app.services.admins import load_roles
from app.services.shops import ShopUrls
from app.shops.context import ShopContext
from app.shops.handlers import build_shop_router
from app.telegram.gateway import BotGateway, GatewayError

log = logging.getLogger(__name__)

SYNC_CONCURRENCY = 10  # параллельных запросов к Telegram при старте


def default_bot_factory(token: str) -> Bot:
    return Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


@dataclass
class SyncReport:
    ok: list[int] = field(default_factory=list)
    failed: list[int] = field(default_factory=list)


class ShopEngine:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        cipher: TokenCipher,
        gateway: BotGateway,
        *,
        public_url: str,
        webhook_master_secret: str,
        bot_factory: Callable[[str], Bot] = default_bot_factory,
    ) -> None:
        self._sm = sessionmaker
        self._cipher = cipher
        self._gw = gateway
        self._urls = ShopUrls(public_url)
        self._master = webhook_master_secret
        self._bot_factory = bot_factory
        self._bots: dict[int, Bot] = {}
        self._lock = asyncio.Lock()
        self.dp = Dispatcher(storage=MemoryStorage())
        self.dp["sessionmaker"] = sessionmaker
        self.dp.include_router(build_shop_router())

    # ── вебхук ──

    def verify_secret(self, shop_id: int, received: str | None) -> bool:
        # Проверка без обращения к БД: подделку отсекаем максимально дёшево
        return secrets_equal(received, shop_webhook_secret(self._master, shop_id))

    async def feed_webhook(self, shop_id: int, payload: dict) -> bool:
        """True — апдейт обработан; False — магазина нет/выключен (апдейт отброшен)."""
        async with self._sm() as s:
            shop = await s.scalar(select(Shop).where(Shop.id == shop_id, Shop.is_active.is_(True)))
            roles = await load_roles(s, shop) if shop else None
        if shop is None:
            log.info("webhook for missing/inactive shop %s dropped", shop_id)
            return False
        bot = await self._get_or_create_bot(shop)
        if bot is None:
            return False
        ctx = ShopContext(
            id=shop.id,
            name=shop.name,
            roles=roles,
            bot_username=shop.bot_username,
            webapp_url=self._urls.webapp(shop.id),
        )
        update = Update.model_validate(payload, context={"bot": bot})
        await self.dp.feed_update(bot, update, shop=ctx)
        return True

    async def _load_active(self, shop_id: int) -> Shop | None:
        async with self._sm() as s:
            return await s.scalar(select(Shop).where(Shop.id == shop_id, Shop.is_active.is_(True)))

    async def _get_or_create_bot(self, shop: Shop) -> Bot | None:
        bot = self._bots.get(shop.id)
        if bot is not None:
            return bot
        async with self._lock:
            bot = self._bots.get(shop.id)  # мог создаться, пока ждали lock
            if bot is None:
                try:
                    token = self._cipher.decrypt(shop.bot_token_encrypted)
                except TokenDecryptError:
                    log.error("shop %s: cannot decrypt token (FERNET_KEY changed?)", shop.id)
                    return None
                bot = self._bot_factory(token)
                self._bots[shop.id] = bot
            return bot

    async def get_bot(self, shop_id: int) -> Bot | None:
        """Бот активного магазина — для исходящих сообщений (уведомления, этап 7)."""
        shop = await self._load_active(shop_id)
        return await self._get_or_create_bot(shop) if shop else None

    # ── жизненный цикл ──

    async def sync_all(self) -> SyncReport:
        """При старте: для каждого активного магазина заново выставить вебхук и кнопку меню.
        Самолечение: если сменился PUBLIC_URL или вебхук слетел — всё вернётся."""
        async with self._sm() as s:
            shops = list(await s.scalars(select(Shop).where(Shop.is_active.is_(True)).order_by(Shop.id)))

        report = SyncReport()
        sem = asyncio.Semaphore(SYNC_CONCURRENCY)

        async def one(shop: Shop) -> None:
            async with sem:
                try:
                    token = self._cipher.decrypt(shop.bot_token_encrypted)
                    await self._gw.configure_shop_bot(
                        token,
                        webhook_url=self._urls.webhook(shop.id),
                        secret=shop_webhook_secret(self._master, shop.id),
                        webapp_url=self._urls.webapp(shop.id),
                        drop_pending_updates=False,
                    )
                    report.ok.append(shop.id)
                except (GatewayError, TokenDecryptError) as e:
                    # Один сломанный магазин (например, токен отозван) не мешает остальным
                    log.warning("shop %s: sync failed (%s)", shop.id, type(e).__name__)
                    report.failed.append(shop.id)

        await asyncio.gather(*(one(shop) for shop in shops))
        log.info("shops synced: %d ok, %d failed", len(report.ok), len(report.failed))
        return report

    async def shop_deactivated(self, shop_id: int) -> None:
        bot = self._bots.pop(shop_id, None)
        if bot is not None:
            await bot.session.close()

    async def close(self) -> None:
        for bot in self._bots.values():
            await bot.session.close()
        self._bots.clear()
