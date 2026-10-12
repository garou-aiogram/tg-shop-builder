"""Обработчики ботов МАГАЗИНОВ. Один router/Dispatcher на все магазины:
какой именно магазин — приходит в kwargs как `shop: ShopContext`."""
from __future__ import annotations

import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import ErrorEvent, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Shop
from app.services.admins import INVITE_PREFIX, AdminError, redeem_invite
from app.shops.context import ShopContext

log = logging.getLogger(__name__)


def open_shop_kb(shop: ShopContext) -> InlineKeyboardMarkup:
    # Inline-кнопка web_app открывает Mini App с initData — так же, как кнопка меню.
    # Дублируем её в сообщении: кнопку меню клиенты Telegram иногда кешируют.
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Open", web_app=WebAppInfo(url=shop.webapp_url))]]
    )


def welcome_text(shop: ShopContext, user_id: int | None) -> str:
    text = (
        f"Добро пожаловать в <b>{escape(shop.name)}</b>!\n\n"
        "Каталог, корзина и оформление заказа — по кнопке «Open» ниже "
        "или слева от поля ввода."
    )
    if shop.is_main_admin(user_id):
        text += (
            "\n\n🔑 <b>Вы главный администратор этого магазина.</b> "
            "Товары, категории, заказы и другие администраторы — в разделе «Админка» внутри магазина. "
            "Сюда будут приходить уведомления о новых заказах."
        )
    elif shop.is_admin(user_id):
        text += (
            "\n\n🔑 <b>Вы администратор этого магазина.</b> "
            "Товары, категории и заказы — в разделе «Админка» внутри магазина. "
            "Сюда будут приходить уведомления о новых заказах."
        )
    return text


def build_shop_router() -> Router:
    # Фабрика, а не модульный router: каждый движок (и каждый тест) получает свой экземпляр
    router = Router(name="shop")
    router.message.filter(F.chat.type == "private")

    @router.message(CommandStart(deep_link=True, magic=F.args.startswith(INVITE_PREFIX)))
    async def accept_invite(
        message: Message, command: CommandObject, shop: ShopContext, bot: Bot,
        sessionmaker: async_sessionmaker[AsyncSession],
    ) -> None:
        user = message.from_user
        token = command.args[len(INVITE_PREFIX):]
        name = " ".join(filter(None, [user.first_name, user.last_name]))
        async with sessionmaker() as s:
            db_shop = await s.get(Shop, shop.id)
            try:
                await redeem_invite(s, db_shop, token, user_id=user.id, name=name, username=user.username)
            except AdminError as e:
                await message.answer(f"❌ {e.message}", reply_markup=open_shop_kb(shop))
                return
        await message.answer(
            f"✅ Вы стали администратором магазина <b>{escape(shop.name)}</b>.\n\n"
            "Откройте магазин кнопкой «Open» — там появился раздел «Админка».",
            reply_markup=open_shop_kb(shop),
        )
        who = f"@{escape(user.username)}" if user.username else f'<a href="tg://user?id={user.id}">{escape(name)}</a>'
        try:
            await bot.send_message(shop.roles.main_admin_id, f"👤 {who} принял приглашение и стал администратором.")
        except Exception:  # noqa: BLE001 — главный админ мог не запускать бота; не критично
            log.info("shop %s: cannot notify main admin about new admin", shop.id)

    @router.message(CommandStart())
    async def start(message: Message, shop: ShopContext) -> None:
        user_id = message.from_user.id if message.from_user else None
        await message.answer(welcome_text(shop, user_id), reply_markup=open_shop_kb(shop))

    @router.message()
    async def fallback(message: Message, shop: ShopContext) -> None:
        await message.answer("Все покупки — в магазине 👇", reply_markup=open_shop_kb(shop))

    @router.error()
    async def on_error(event: ErrorEvent, bot: Bot) -> bool:
        log.exception("shop bot handler failed", exc_info=event.exception)
        return True  # вебхук ответит 200 — Telegram не будет бесконечно ретраить

    return router
