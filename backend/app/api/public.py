"""API покупателя: магазин, каталог, корзина, заказы.
Все запросы — в рамках одного магазина (shop_id из URL) и одного пользователя (из initData)."""
from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import case, desc, or_, select
from sqlalchemy.orm import selectinload

from app.api.deps import CtxDep, Session
from app.api.schemas import (
    CartItemOut, CartOut, CartQuantityIn, CategoryOut, MeOut, OrderIn, OrderOut, ProductOut, ProductSort, ShopOut,
)
from app.db.models import CartItem, Category, Order, OrderStatus, Product
from app.services.orders import OrderError, create_order

router = APIRouter(prefix="/api/shops/{shop_id}")


def escape_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def order_error_response(e: OrderError) -> JSONResponse:
    return JSONResponse(status_code=e.status_code, content={"detail": e.message, **e.details})


# ── магазин ──

@router.get("/me", response_model=MeOut)
async def me(ctx: CtxDep) -> MeOut:
    return MeOut(
        user_id=ctx.user.id,
        first_name=ctx.user.first_name,
        is_admin=ctx.is_admin,
        is_main_admin=ctx.is_main_admin,
        shop=ShopOut(id=ctx.shop.id, name=ctx.shop.name, bot_username=ctx.shop.bot_username),
    )


# ── каталог ──

@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(ctx: CtxDep, session: Session):
    return await session.scalars(
        select(Category).where(Category.shop_id == ctx.shop_id).order_by(Category.sort_order, Category.name)
    )


@router.get("/products", response_model=list[ProductOut])
async def list_products(
    ctx: CtxDep,
    session: Session,
    q: Annotated[str | None, Query(max_length=100)] = None,
    category_id: int | None = None,
    sort: ProductSort = "new",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    stmt = select(Product).where(Product.shop_id == ctx.shop_id).options(selectinload(Product.images))
    if category_id is not None:
        stmt = stmt.where(Product.category_id == category_id)
    if q and q.strip():
        pattern = f"%{escape_like(q.strip())}%"
        stmt = stmt.where(or_(Product.name.ilike(pattern, escape="\\"), Product.description.ilike(pattern, escape="\\")))

    discount = case(
        (Product.old_price > Product.price, (Product.old_price - Product.price) / Product.old_price), else_=0
    )
    order_by = {
        "new": [desc(Product.id)],
        "price_asc": [Product.price, Product.id],
        "price_desc": [desc(Product.price), Product.id],
        "discount": [desc(discount), desc(Product.id)],
    }[sort]
    # Товары в наличии — всегда выше отсутствующих
    stmt = stmt.order_by(desc(Product.in_stock), *order_by).limit(limit).offset(offset)
    return [ProductOut.from_model(p) for p in await session.scalars(stmt)]


@router.get("/products/{product_id}", response_model=ProductOut)
async def get_product(product_id: int, ctx: CtxDep, session: Session):
    p = await session.scalar(
        select(Product).where(Product.id == product_id, Product.shop_id == ctx.shop_id).options(selectinload(Product.images))
    )
    if p is None:
        raise HTTPException(404, "Товар не найден")
    return ProductOut.from_model(p)


# ── корзина ──

async def build_cart(session, shop_id: int, user_id: int) -> CartOut:
    items = await session.scalars(
        select(CartItem)
        .where(CartItem.shop_id == shop_id, CartItem.user_id == user_id)
        .options(selectinload(CartItem.product).selectinload(Product.images))
        .order_by(CartItem.id)
        .execution_options(populate_existing=True)
    )
    out = [
        CartItemOut(product=ProductOut.from_model(c.product), quantity=c.quantity, subtotal=c.product.price * c.quantity)
        for c in items
    ]
    return CartOut(items=out, total=sum((i.subtotal for i in out), Decimal("0")), count=sum(i.quantity for i in out))


@router.get("/cart", response_model=CartOut)
async def get_cart(ctx: CtxDep, session: Session):
    return await build_cart(session, ctx.shop_id, ctx.user.id)


@router.put("/cart/items/{product_id}", response_model=CartOut)
async def set_cart_quantity(product_id: int, body: CartQuantityIn, ctx: CtxDep, session: Session):
    product = await session.scalar(select(Product).where(Product.id == product_id, Product.shop_id == ctx.shop_id))
    if product is None:
        raise HTTPException(404, "Товар не найден")
    item = await session.scalar(
        select(CartItem).where(
            CartItem.shop_id == ctx.shop_id, CartItem.user_id == ctx.user.id, CartItem.product_id == product_id
        )
    )
    if body.quantity == 0:
        if item is not None:
            await session.delete(item)
    else:
        if not product.in_stock:
            raise HTTPException(409, "Товара нет в наличии")
        if item is None:
            session.add(CartItem(shop_id=ctx.shop_id, user_id=ctx.user.id, product_id=product_id, quantity=body.quantity))
        else:
            item.quantity = body.quantity
    await session.commit()
    return await build_cart(session, ctx.shop_id, ctx.user.id)


@router.delete("/cart", response_model=CartOut)
async def clear_cart(ctx: CtxDep, session: Session):
    for item in await session.scalars(
        select(CartItem).where(CartItem.shop_id == ctx.shop_id, CartItem.user_id == ctx.user.id)
    ):
        await session.delete(item)
    await session.commit()
    return await build_cart(session, ctx.shop_id, ctx.user.id)


# ── заказы ──

@router.post("/orders", response_model=OrderOut, status_code=201)
async def place_order(body: OrderIn, ctx: CtxDep, session: Session):
    try:
        order = await create_order(
            session, shop_id=ctx.shop_id, user_id=ctx.user.id, data=body,
            tg_username=ctx.user.username, tg_name=ctx.display_name,
        )
    except OrderError as e:
        return order_error_response(e)
    # Уведомление администратора — этап 7 (хук в app.state.order_events)
    return order


@router.get("/orders", response_model=list[OrderOut])
async def my_orders(
    ctx: CtxDep,
    session: Session,
    scope: Annotated[str, Query(pattern="^(active|finished|all)$")] = "all",
):
    stmt = (
        select(Order)
        .where(Order.shop_id == ctx.shop_id, Order.user_id == ctx.user.id)
        .options(selectinload(Order.items))
        .order_by(desc(Order.id))
    )
    if scope == "active":
        stmt = stmt.where(Order.status.in_(OrderStatus.active()))
    elif scope == "finished":
        stmt = stmt.where(Order.status.in_(OrderStatus.finished()))
    return await session.scalars(stmt)
