"""Главный бот-конструктор: меню, создание магазина (FSM), «Мои магазины»."""
from __future__ import annotations

import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ErrorEvent, Message

from app.builder.keyboards import MenuCb, ShopCb, admin_step_kb, cancel_kb, main_menu, shop_card_kb, shops_list_kb
from app.builder.states import ChangeAdmin, CreateShop
from app.db.models import Shop
from app.security.crypto import TokenCipher
from app.services.shops import (
    ShopError,
    ShopService,
    parse_telegram_id,
    validate_shop_name,
    validate_token_format,
)

log = logging.getLogger(__name__)
router = Router(name="builder")
router.message.filter(F.chat.type == "private")

HOME_TEXT = (
    "<b>Конструктор магазинов в Telegram</b>\n\n"
    "Подключите своего бота — и он станет магазином с каталогом, корзиной и заказами."
)
TOKEN_PROMPT = (
    "<b>Шаг 1 из 3.</b> Пришлите токен вашего бота.\n\n"
    "Где взять: @BotFather → /newbot (или /mybots → бот → API Token).\n"
    "Сообщение с токеном я сразу удалю из чата."
)
ADMIN_PROMPT = (
    "<b>Шаг 2 из 3.</b> Кто будет администратором магазина?\n\n"
    "Пришлите его Telegram ID (число) или нажмите кнопку, если это вы. "
    "Администратор управляет товарами и получает уведомления о заказах."
)
NAME_PROMPT = "<b>Шаг 3 из 3.</b> Как назовём магазин? (до 64 символов)"


def shop_card_text(shop: Shop) -> str:
    status = "🟢 работает" if shop.is_active else "⚪️ выключен"
    return (
        f"<b>{escape(shop.name)}</b>\n\n"
        f"Бот: @{escape(shop.bot_username)}\n"
        f"Администратор: <code>{shop.admin_id}</code>\n"
        f"Статус: {status}"
    )


async def safe_edit(cb: CallbackQuery, text: str, markup) -> None:
    try:
        await cb.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        # «message is not modified» или сообщение слишком старое — просто шлём новое
        await cb.message.answer(text, reply_markup=markup)


# ─── Главное меню ───────────────────────────────────────────────────────


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(HOME_TEXT, reply_markup=main_menu())


@router.callback_query(MenuCb.filter(F.action.in_({"home", "cancel"})))
async def go_home(cb: CallbackQuery, callback_data: MenuCb, state: FSMContext) -> None:
    await state.clear()
    await safe_edit(cb, HOME_TEXT, main_menu())
    await cb.answer("Отменено" if callback_data.action == "cancel" else None)


# ─── Создание магазина ──────────────────────────────────────────────────


@router.callback_query(MenuCb.filter(F.action == "create"))
async def create_start(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(CreateShop.token)
    await safe_edit(cb, TOKEN_PROMPT, cancel_kb())
    await cb.answer()


@router.message(CreateShop.token, F.text)
async def create_token(message: Message, state: FSMContext, shop_service: ShopService, cipher: TokenCipher) -> None:
    raw = message.text or ""
    try:
        await message.delete()  # токен не должен оставаться в истории чата
    except TelegramBadRequest:
        pass
    try:
        token = validate_token_format(raw)
    except ShopError as e:
        await message.answer(f"❌ {e.user_message}\n\n{TOKEN_PROMPT}", reply_markup=cancel_kb())
        return
    # Сообщение «проверяю» потом заменяется результатом — в чате не остаётся мусора
    wait = await message.answer("⏳ Проверяю токен…")
    try:
        identity = await shop_service.check_token(token)
    except ShopError as e:
        await wait.edit_text(f"❌ {e.user_message}\n\n{TOKEN_PROMPT}", reply_markup=cancel_kb())
        return
    # В FSM кладём только шифротекст
    await state.update_data(token_enc=cipher.encrypt(token), bot_username=identity.username)
    await state.set_state(CreateShop.admin_id)
    await wait.edit_text(f"✅ Бот @{escape(identity.username)} найден.\n\n{ADMIN_PROMPT}", reply_markup=admin_step_kb())


@router.callback_query(CreateShop.admin_id, MenuCb.filter(F.action == "admin_me"))
async def create_admin_me(cb: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(admin_id=cb.from_user.id)
    await state.set_state(CreateShop.name)
    await safe_edit(cb, f"👤 Администратор: вы (<code>{cb.from_user.id}</code>).\n\n{NAME_PROMPT}", cancel_kb())
    await cb.answer()


@router.message(CreateShop.admin_id, F.text)
async def create_admin_id(message: Message, state: FSMContext) -> None:
    try:
        admin_id = parse_telegram_id(message.text or "")
    except ShopError as e:
        await message.answer(f"❌ {e.user_message}", reply_markup=admin_step_kb())
        return
    await state.update_data(admin_id=admin_id)
    await state.set_state(CreateShop.name)
    await message.answer(f"👤 Администратор: <code>{admin_id}</code>.\n\n{NAME_PROMPT}", reply_markup=cancel_kb())


@router.message(CreateShop.name, F.text)
async def create_name(message: Message, state: FSMContext, shop_service: ShopService, cipher: TokenCipher) -> None:
    try:
        name = validate_shop_name(message.text or "")
    except ShopError as e:
        await message.answer(f"❌ {e.user_message}", reply_markup=cancel_kb())
        return

    data = await state.get_data()
    wait = await message.answer("⏳ Создаю магазин и настраиваю бота…")
    try:
        shop = await shop_service.create_shop(
            owner_id=message.from_user.id,
            token=cipher.decrypt(data["token_enc"]),
            admin_id=data["admin_id"],
            name=name,
        )
    except ShopError as e:
        await state.clear()
        await wait.edit_text(f"❌ {e.user_message}", reply_markup=main_menu())
        return

    await state.clear()
    await wait.edit_text(
        f"🎉 Магазин <b>{escape(shop.name)}</b> создан!\n\n"
        f"Откройте @{escape(shop.bot_username)} — внизу слева появилась кнопка «Магазин», "
        f"она открывает витрину. Администратор управляет товарами там же.",
        reply_markup=shop_card_kb(shop),
    )


# ─── Мои магазины ───────────────────────────────────────────────────────


@router.callback_query(MenuCb.filter(F.action == "list"))
async def my_shops(cb: CallbackQuery, state: FSMContext, shop_service: ShopService) -> None:
    await state.clear()
    shops = await shop_service.list_shops(cb.from_user.id)
    text = "<b>Мои магазины</b>" if shops else "У вас пока нет магазинов."
    await safe_edit(cb, text, shops_list_kb(shops))
    await cb.answer()


@router.callback_query(ShopCb.filter(F.action == "view"))
async def shop_view(cb: CallbackQuery, callback_data: ShopCb, shop_service: ShopService) -> None:
    try:
        shop = await shop_service.get_owned_shop(cb.from_user.id, callback_data.shop_id)
    except ShopError as e:
        await cb.answer(e.user_message, show_alert=True)
        return
    await safe_edit(cb, shop_card_text(shop), shop_card_kb(shop))
    await cb.answer()


@router.callback_query(ShopCb.filter(F.action.in_({"on", "off"})))
async def shop_toggle(cb: CallbackQuery, callback_data: ShopCb, shop_service: ShopService) -> None:
    try:
        shop = await shop_service.set_active(cb.from_user.id, callback_data.shop_id, callback_data.action == "on")
    except ShopError as e:
        await cb.answer(e.user_message, show_alert=True)
        return
    await safe_edit(cb, shop_card_text(shop), shop_card_kb(shop))
    await cb.answer("Магазин включён" if shop.is_active else "Магазин выключен")


@router.callback_query(ShopCb.filter(F.action == "admin"))
async def shop_admin_start(cb: CallbackQuery, callback_data: ShopCb, state: FSMContext, shop_service: ShopService) -> None:
    try:
        shop = await shop_service.get_owned_shop(cb.from_user.id, callback_data.shop_id)
    except ShopError as e:
        await cb.answer(e.user_message, show_alert=True)
        return
    await state.set_state(ChangeAdmin.admin_id)
    await state.update_data(shop_id=shop.id)
    await safe_edit(cb, f"Пришлите новый Telegram ID администратора магазина <b>{escape(shop.name)}</b>.", cancel_kb())
    await cb.answer()


@router.message(ChangeAdmin.admin_id, F.text)
async def shop_admin_set(message: Message, state: FSMContext, shop_service: ShopService) -> None:
    try:
        admin_id = parse_telegram_id(message.text or "")
        shop_id = (await state.get_data())["shop_id"]
        shop = await shop_service.change_admin(message.from_user.id, shop_id, admin_id)
    except ShopError as e:
        await message.answer(f"❌ {e.user_message}", reply_markup=cancel_kb())
        return
    await state.clear()
    await message.answer("✅ Администратор изменён.\n\n" + shop_card_text(shop), reply_markup=shop_card_kb(shop))


# ─── Прочее ─────────────────────────────────────────────────────────────
# Порядок важен: aiogram берёт первый подходящий обработчик, поэтому
# «ловушки» регистрируются после всех конкретных обработчиков.


@router.message(CreateShop.token)
@router.message(CreateShop.admin_id)
@router.message(CreateShop.name)
@router.message(ChangeAdmin.admin_id)
async def expect_text(message: Message) -> None:
    await message.answer("Пришлите, пожалуйста, текстовое сообщение.", reply_markup=cancel_kb())


@router.message()
async def fallback(message: Message) -> None:
    await message.answer(HOME_TEXT, reply_markup=main_menu())


@router.error()
async def on_error(event: ErrorEvent, bot: Bot) -> bool:
    log.exception("builder handler failed", exc_info=event.exception)
    chat = None
    if event.update.message:
        chat = event.update.message.chat.id
    elif event.update.callback_query and event.update.callback_query.message:
        chat = event.update.callback_query.message.chat.id
    if chat is not None:
        try:
            await bot.send_message(chat, "Что-то пошло не так. Нажмите /start и попробуйте ещё раз.")
        except Exception:  # noqa: BLE001
            pass
    return True  # ошибка обработана — вебхук ответит 200, Telegram не будет ретраить
