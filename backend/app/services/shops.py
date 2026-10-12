"""Бизнес-логика магазинов для главного бота.

Все операции над существующим магазином идут через _get_owned(): владение
проверяется на сервере по owner_id при каждом действии, а не только при показе
кнопок (callback_data можно подделать).
"""
from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Shop, ShopAdmin
from app.security.crypto import TokenCipher, TokenDecryptError
from app.security.webhook import shop_webhook_secret
from app.telegram.gateway import BotGateway, BotIdentity, TelegramUnavailable, TokenRejected

log = logging.getLogger(__name__)

TOKEN_FORMAT = re.compile(r"^(\d{5,20}):[A-Za-z0-9_-]{30,64}$")
SHOP_NAME_MAX = 64
TELEGRAM_ID_MAX = 2**52  # реальные id заметно меньше; отсекаем мусор и переполнение BigInteger


# ─── Ошибки: у каждой есть текст для пользователя ───────────────────────


class ShopError(Exception):
    user_message = "Что-то пошло не так. Попробуйте ещё раз."

    def __init__(self, user_message: str | None = None) -> None:
        super().__init__(user_message or self.user_message)
        if user_message:
            self.user_message = user_message


class InvalidInput(ShopError):
    pass


class InvalidToken(ShopError):
    user_message = "Telegram не принял этот токен. Проверьте, что скопировали его из @BotFather целиком."


class BotAlreadyUsed(ShopError):
    user_message = "Этот бот уже подключён к другому магазину. Создайте нового бота в @BotFather."


class BuilderTokenUsed(ShopError):
    user_message = "Это токен самого конструктора. Нужен токен другого бота."


class TelegramFailed(ShopError):
    user_message = "Не удалось связаться с Telegram. Попробуйте через минуту."


class ShopNotFound(ShopError):
    user_message = "Магазин не найден."


# ─── Валидация ввода (чистые функции, покрыты тестами) ──────────────────


def validate_token_format(raw: str) -> str:
    token = raw.strip()
    if not TOKEN_FORMAT.match(token):
        raise InvalidInput("Это не похоже на токен. Он выглядит так: <code>123456789:AAH...</code>")
    return token


def parse_telegram_id(raw: str) -> int:
    text = raw.strip()
    if not text.isdigit():
        raise InvalidInput("ID — это число, например <code>123456789</code>. Узнать свой можно у @userinfobot.")
    value = int(text)
    if not 0 < value < TELEGRAM_ID_MAX:
        raise InvalidInput("Такого Telegram ID не бывает. Проверьте число.")
    return value


def validate_shop_name(raw: str) -> str:
    name = " ".join(raw.split())  # схлопываем пробелы и переводы строк
    if not name:
        raise InvalidInput("Название не может быть пустым.")
    if len(name) > SHOP_NAME_MAX:
        raise InvalidInput(f"Слишком длинно: максимум {SHOP_NAME_MAX} символа.")
    return name


def bot_id_from_token(token: str) -> int:
    return int(token.split(":", 1)[0])


# ─── Сервис ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ShopUrls:
    public_url: str

    def webhook(self, shop_id: int) -> str:
        return f"{self.public_url}/webhook/{shop_id}"

    def webapp(self, shop_id: int) -> str:
        return f"{self.public_url}/?shop={shop_id}"


class ShopService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        cipher: TokenCipher,
        gateway: BotGateway,
        *,
        public_url: str,
        webhook_master_secret: str,
        builder_bot_id: int,
    ) -> None:
        self._sm = sessionmaker
        self._cipher = cipher
        self._gw = gateway
        self.urls = ShopUrls(public_url)
        self._master = webhook_master_secret
        self._builder_bot_id = builder_bot_id
        # Хук для движка магазинов (закрыть сессию бота выключенного магазина).
        # Колбэк, а не импорт движка — чтобы не было циклической зависимости.
        self.on_deactivated: Callable[[int], Awaitable[None]] | None = None

    # ── проверка токена (шаг 1 FSM) ──

    async def check_token(self, token: str) -> BotIdentity:
        """Формат → не конструктор → не занят → getMe. Дешёвые проверки до сетевой."""
        token = validate_token_format(token)
        bot_id = bot_id_from_token(token)
        if bot_id == self._builder_bot_id:
            raise BuilderTokenUsed()
        await self._ensure_bot_free(bot_id)
        identity = await self._get_me(token)
        if identity.id == self._builder_bot_id:
            raise BuilderTokenUsed()
        return identity

    async def _ensure_bot_free(self, bot_id: int) -> None:
        async with self._sm() as s:
            if await s.scalar(select(Shop.id).where(Shop.bot_id == bot_id)) is not None:
                raise BotAlreadyUsed()

    async def _get_me(self, token: str) -> BotIdentity:
        try:
            return await self._gw.get_me(token)
        except TokenRejected as e:
            raise InvalidToken() from e
        except TelegramUnavailable as e:
            raise TelegramFailed() from e

    # ── создание ──

    async def create_shop(self, *, owner_id: int, token: str, admin_id: int, name: str) -> Shop:
        token = validate_token_format(token)
        name = validate_shop_name(name)
        identity = await self.check_token(token)  # повторно: между шагами FSM бот могли занять

        async with self._sm() as s:
            shop = Shop(
                owner_id=owner_id,
                admin_id=admin_id,
                name=name,
                bot_token_encrypted=self._cipher.encrypt(token),
                bot_id=identity.id,
                bot_username=identity.username,
                is_active=True,
            )
            s.add(shop)
            try:
                await s.flush()  # нужен shop.id для URL вебхука и Mini App
            except IntegrityError as e:
                # гонка: тот же бот подключили параллельно — сработал UNIQUE(bot_id)
                raise BotAlreadyUsed() from e

            try:
                await self._configure(token, shop.id)
            except ShopError:
                await s.rollback()
                await self._best_effort_disable(token)  # вебхук мог успеть встать
                raise
            await s.commit()

        log.info("shop created: id=%s bot=@%s owner=%s", shop.id, shop.bot_username, owner_id)
        return shop

    async def _configure(self, token: str, shop_id: int) -> None:
        try:
            await self._gw.configure_shop_bot(
                token,
                webhook_url=self.urls.webhook(shop_id),
                secret=shop_webhook_secret(self._master, shop_id),
                webapp_url=self.urls.webapp(shop_id),
            )
        except TokenRejected as e:
            raise InvalidToken() from e
        except TelegramUnavailable as e:
            raise TelegramFailed() from e

    async def _best_effort_disable(self, token: str) -> None:
        try:
            await self._gw.disable_shop_bot(token)
        except Exception:  # noqa: BLE001 — это уборка после ошибки, основную ошибку не маскируем
            log.warning("cleanup after failed shop setup did not complete")

    # ── управление (только владелец) ──

    async def list_shops(self, owner_id: int) -> list[Shop]:
        async with self._sm() as s:
            rows = await s.scalars(select(Shop).where(Shop.owner_id == owner_id).order_by(Shop.id))
            return list(rows)

    async def get_owned_shop(self, owner_id: int, shop_id: int) -> Shop:
        async with self._sm() as s:
            return await self._get_owned(s, owner_id, shop_id)

    @staticmethod
    async def _get_owned(s: AsyncSession, owner_id: int, shop_id: int) -> Shop:
        shop = await s.scalar(select(Shop).where(Shop.id == shop_id, Shop.owner_id == owner_id))
        if shop is None:
            # Одинаковый ответ для «нет такого» и «чужой» — не раскрываем чужие id
            raise ShopNotFound()
        return shop

    async def set_active(self, owner_id: int, shop_id: int, active: bool) -> Shop:
        async with self._sm() as s:
            shop = await self._get_owned(s, owner_id, shop_id)
            if shop.is_active == active:
                return shop
            token = self._decrypt(shop)
            if active:
                await self._configure(token, shop.id)
            else:
                try:
                    await self._gw.disable_shop_bot(token)
                except TokenRejected:
                    # токен отозван — бот и так мёртв, магазин всё равно выключаем
                    log.info("shop %s: token rejected while disabling", shop.id)
                except TelegramUnavailable as e:
                    raise TelegramFailed() from e
            shop.is_active = active
            await s.commit()
            log.info("shop %s active=%s by owner %s", shop.id, active, owner_id)
        if not active and self.on_deactivated is not None:
            await self.on_deactivated(shop.id)
        return shop

    async def change_admin(self, owner_id: int, shop_id: int, admin_id: int) -> Shop:
        async with self._sm() as s:
            shop = await self._get_owned(s, owner_id, shop_id)
            shop.admin_id = admin_id
            # Новый главный админ, если был дополнительным, — больше не дубль в списке
            await s.execute(delete(ShopAdmin).where(ShopAdmin.shop_id == shop.id, ShopAdmin.user_id == admin_id))
            await s.commit()
            log.info("shop %s admin changed by owner %s", shop.id, owner_id)
            return shop

    def _decrypt(self, shop: Shop) -> str:
        try:
            return self._cipher.decrypt(shop.bot_token_encrypted)
        except TokenDecryptError as e:
            log.error("shop %s: cannot decrypt token (FERNET_KEY changed?)", shop.id)
            raise ShopError("Не удалось прочитать токен магазина. Обратитесь к администратору сервиса.") from e
