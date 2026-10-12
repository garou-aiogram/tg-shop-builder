"""Заказы: создание из корзины и смена статуса.

Цена и название в заказе — снимок на момент оформления (order_items),
итог считается на сервере. Клиент присылает только контакты и способ получения.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import CartItem, Order, OrderItem, OrderStatus, PaymentMethod

# Разрешённые переходы статусов. Завершённые заказы не «оживают».
TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.NEW: {OrderStatus.IN_PROGRESS, OrderStatus.DONE, OrderStatus.CANCELLED},
    OrderStatus.IN_PROGRESS: {OrderStatus.DONE, OrderStatus.CANCELLED, OrderStatus.NEW},
    OrderStatus.DONE: set(),
    OrderStatus.CANCELLED: set(),
}


class OrderError(Exception):
    def __init__(self, message: str, status_code: int = 409, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details or {}


async def create_order(
    session: AsyncSession, *, shop_id: int, user_id: int, data,
    tg_username: str | None = None, tg_name: str | None = None,
) -> Order:
    # FOR UPDATE: два одновременных «Оформить» от одного пользователя не создадут два заказа
    cart = list(
        await session.scalars(
            select(CartItem)
            .where(CartItem.shop_id == shop_id, CartItem.user_id == user_id)
            .options(selectinload(CartItem.product))
            .order_by(CartItem.id)
            .with_for_update(of=CartItem)
        )
    )
    if not cart:
        raise OrderError("Корзина пуста")

    unavailable = [c.product.name for c in cart if not c.product.in_stock]
    if unavailable:
        raise OrderError(
            "Некоторых товаров нет в наличии — уберите их из корзины",
            details={"unavailable": unavailable},
        )

    order = Order(
        shop_id=shop_id,
        user_id=user_id,
        customer_name=data.customer_name,
        phone=data.phone,
        tg_username=tg_username,
        tg_name=(tg_name or "")[:128] or None,
        delivery_method=data.delivery_method,
        address=data.address,
        comment=data.comment,
        total=Decimal("0"),
        status=OrderStatus.NEW,
        payment_method=PaymentMethod.MANUAL,  # точка расширения: модуль оплаты подставит свой
    )
    total = Decimal("0")
    for c in cart:
        order.items.append(
            OrderItem(product_id=c.product_id, product_name=c.product.name, price=c.product.price, quantity=c.quantity)
        )
        total += c.product.price * c.quantity
    order.total = total

    session.add(order)
    await session.execute(delete(CartItem).where(CartItem.shop_id == shop_id, CartItem.user_id == user_id))
    await session.commit()
    return await load_order(session, shop_id, order.id)


async def load_order(session: AsyncSession, shop_id: int, order_id: int) -> Order | None:
    return await session.scalar(
        select(Order)
        .where(Order.id == order_id, Order.shop_id == shop_id)
        .options(selectinload(Order.items))
        .execution_options(populate_existing=True)
    )


async def change_status(session: AsyncSession, *, shop_id: int, order_id: int, new: OrderStatus) -> tuple[Order, OrderStatus]:
    order = await session.scalar(
        select(Order).where(Order.id == order_id, Order.shop_id == shop_id).with_for_update()
    )
    if order is None:
        raise OrderError("Заказ не найден", status_code=404)
    old = order.status
    if new == old:
        return await load_order(session, shop_id, order_id), old
    if new not in TRANSITIONS[old]:
        raise OrderError(f"Нельзя сменить статус «{old.value}» на «{new.value}»")
    order.status = new
    await session.commit()
    return await load_order(session, shop_id, order_id), old
