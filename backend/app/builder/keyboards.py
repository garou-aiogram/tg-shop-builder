from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models import Shop


class MenuCb(CallbackData, prefix="m"):
    action: str  # create | list | cancel | home | admin_me


class ShopCb(CallbackData, prefix="s"):
    action: str  # view | on | off | admin
    shop_id: int


def main_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="➕ Создать магазин", callback_data=MenuCb(action="create"))
    b.button(text="🏪 Мои магазины", callback_data=MenuCb(action="list"))
    b.adjust(1)
    return b.as_markup()


def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✖️ Отмена", callback_data=MenuCb(action="cancel").pack())]]
    )


def admin_step_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="👤 Администратор — я", callback_data=MenuCb(action="admin_me"))
    b.button(text="✖️ Отмена", callback_data=MenuCb(action="cancel"))
    b.adjust(1)
    return b.as_markup()


def shops_list_kb(shops: list[Shop]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for shop in shops:
        mark = "🟢" if shop.is_active else "⚪️"
        b.button(text=f"{mark} {shop.name}", callback_data=ShopCb(action="view", shop_id=shop.id))
    b.button(text="⬅️ Назад", callback_data=MenuCb(action="home"))
    b.adjust(1)
    return b.as_markup()


def shop_card_kb(shop: Shop) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🤖 Открыть бота", url=f"https://t.me/{shop.bot_username}")
    if shop.is_active:
        b.button(text="⏸ Выключить", callback_data=ShopCb(action="off", shop_id=shop.id))
    else:
        b.button(text="▶️ Включить", callback_data=ShopCb(action="on", shop_id=shop.id))
    b.button(text="👤 Сменить администратора", callback_data=ShopCb(action="admin", shop_id=shop.id))
    b.button(text="⬅️ К списку", callback_data=MenuCb(action="list"))
    b.adjust(1)
    return b.as_markup()
