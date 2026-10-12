"""Операции с ботами магазинов через Telegram Bot API.

Вынесено за интерфейс BotGateway, чтобы сервисный слой тестировался без сети.
Токен приходит сюда уже расшифрованным и живёт только внутри вызова.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError, TelegramUnauthorizedError
from aiogram.types import MenuButtonDefault, MenuButtonWebApp, WebAppInfo
from aiogram.utils.token import TokenValidationError

log = logging.getLogger(__name__)

# Какие апдейты нужны ботам магазинов (этап 3: /start, кнопки)
SHOP_ALLOWED_UPDATES = ["message", "callback_query"]
MENU_BUTTON_TEXT = "Open"


@dataclass(frozen=True)
class BotIdentity:
    id: int
    username: str
    first_name: str


class GatewayError(Exception):
    pass


class TokenRejected(GatewayError):
    """Telegram не принял токен: неверный, отозван или бот удалён."""


class TelegramUnavailable(GatewayError):
    """Сеть/Telegram недоступны или вернули неожиданную ошибку."""


class BotGateway(Protocol):
    async def get_me(self, token: str) -> BotIdentity: ...

    async def configure_shop_bot(
        self, token: str, *, webhook_url: str, secret: str, webapp_url: str, drop_pending_updates: bool = True
    ) -> None: ...

    async def disable_shop_bot(self, token: str) -> None: ...


class AiogramBotGateway:
    """Реализация через aiogram. Для каждой операции — короткоживущий Bot,
    сессия закрывается сразу (движок магазинов на этапе 3 держит свои экземпляры)."""

    async def _call(self, token: str, fn):
        try:
            bot = Bot(token)
        except TokenValidationError as e:
            raise TokenRejected("неверный формат токена") from e
        try:
            return await fn(bot)
        except TelegramUnauthorizedError as e:
            raise TokenRejected("Telegram отклонил токен") from e
        except (TelegramNetworkError, TelegramAPIError) as e:
            # В тексте исключения может быть URL с токеном — логируем только тип;
            # форматтер логов всё равно вырежет токен, это вторая линия защиты.
            log.warning("Telegram API error: %s", type(e).__name__)
            raise TelegramUnavailable(type(e).__name__) from e
        finally:
            await bot.session.close()

    async def get_me(self, token: str) -> BotIdentity:
        async def fn(bot: Bot) -> BotIdentity:
            me = await bot.get_me()
            return BotIdentity(id=me.id, username=me.username or "", first_name=me.first_name)

        return await self._call(token, fn)

    async def configure_shop_bot(
        self, token: str, *, webhook_url: str, secret: str, webapp_url: str, drop_pending_updates: bool = True
    ) -> None:
        # drop_pending_updates=True — при создании/включении магазина (старые апдейты
        # от прошлой жизни бота не нужны); False — при рестарте сервиса, чтобы
        # не потерять сообщения, пришедшие, пока backend перезапускался.
        async def fn(bot: Bot) -> None:
            await bot.set_webhook(
                url=webhook_url,
                secret_token=secret,
                allowed_updates=SHOP_ALLOWED_UPDATES,
                drop_pending_updates=drop_pending_updates,
            )
            # Кнопка меню по умолчанию для всех чатов бота открывает Mini App
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(text=MENU_BUTTON_TEXT, web_app=WebAppInfo(url=webapp_url))
            )

        await self._call(token, fn)

    async def disable_shop_bot(self, token: str) -> None:
        async def fn(bot: Bot) -> None:
            await bot.delete_webhook(drop_pending_updates=True)
            await bot.set_chat_menu_button(menu_button=MenuButtonDefault())

        await self._call(token, fn)
