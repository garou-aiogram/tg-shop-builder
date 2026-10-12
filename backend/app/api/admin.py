"""API администратора магазина. Доступ — только если user.id из проверенного
initData совпадает с shops.admin_id (см. deps.require_admin)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response, UploadFile
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.api.deps import AdminDep, MainAdminDep, Session
from app.api.public import order_error_response
from app.api.schemas import (
    AdminAddIn, AdminOrderOut, AdminOut, CategoryIn, CategoryOut, CategoryPatch, ImageOrderIn, InviteOut,
    OrderStatusIn, ProductIn, ProductOut, ProductPatch,
)
from app.db.models import MAX_PRODUCT_IMAGES, Category, Order, OrderStatus, Product, ProductImage
from app.services import admins as admin_svc
from app.services.media import MAX_IMAGE_BYTES, MediaError, MediaStorage
from app.services.orders import OrderError, change_status

router = APIRouter(prefix="/api/shops/{shop_id}/admin")


def media(request: Request) -> MediaStorage:
    return request.app.state.media


async def own_category(session, shop_id: int, category_id: int) -> Category:
    c = await session.scalar(select(Category).where(Category.id == category_id, Category.shop_id == shop_id))
    if c is None:
        raise HTTPException(404, "Категория не найдена")
    return c


async def own_product(session, shop_id: int, product_id: int) -> Product:
    p = await session.scalar(
        select(Product).where(Product.id == product_id, Product.shop_id == shop_id)
        .options(selectinload(Product.images))
        .execution_options(populate_existing=True)
    )
    if p is None:
        raise HTTPException(404, "Товар не найден")
    return p


async def check_category(session, shop_id: int, category_id: int | None) -> None:
    # Нельзя привязать товар к категории ЧУЖОГО магазина
    if category_id is not None:
        await own_category(session, shop_id, category_id)


# ── категории ──

@router.post("/categories", response_model=CategoryOut, status_code=201)
async def create_category(body: CategoryIn, ctx: AdminDep, session: Session):
    c = Category(shop_id=ctx.shop_id, name=body.name, sort_order=body.sort_order)
    session.add(c)
    try:
        await session.commit()
    except IntegrityError:
        raise HTTPException(409, "Категория с таким названием уже есть") from None
    return c


@router.patch("/categories/{category_id}", response_model=CategoryOut)
async def update_category(category_id: int, body: CategoryPatch, ctx: AdminDep, session: Session):
    c = await own_category(session, ctx.shop_id, category_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(c, field, value)
    try:
        await session.commit()
    except IntegrityError:
        raise HTTPException(409, "Категория с таким названием уже есть") from None
    return c


@router.delete("/categories/{category_id}", status_code=204)
async def delete_category(category_id: int, ctx: AdminDep, session: Session):
    # Товары категории не удаляются — становятся «без категории» (ON DELETE SET NULL)
    await session.delete(await own_category(session, ctx.shop_id, category_id))
    await session.commit()
    return Response(status_code=204)


# ── товары ──

@router.post("/products", response_model=ProductOut, status_code=201)
async def create_product(body: ProductIn, ctx: AdminDep, session: Session):
    await check_category(session, ctx.shop_id, body.category_id)
    p = Product(shop_id=ctx.shop_id, images=[], **body.model_dump())
    session.add(p)
    await session.commit()
    return ProductOut.from_model(p)


@router.patch("/products/{product_id}", response_model=ProductOut)
async def update_product(product_id: int, body: ProductPatch, ctx: AdminDep, session: Session):
    p = await own_product(session, ctx.shop_id, product_id)
    changes = body.model_dump(exclude_unset=True)
    for required in ("name", "price", "description", "in_stock"):
        if required in changes and changes[required] is None:
            raise HTTPException(422, f"Поле {required} не может быть пустым")
    if "category_id" in changes:
        await check_category(session, ctx.shop_id, changes["category_id"])
    new_price = changes.get("price", p.price)
    new_old = changes.get("old_price", p.old_price)
    if new_old is not None and new_old <= new_price:
        raise HTTPException(422, "Старая цена должна быть больше текущей")
    for field, value in changes.items():
        setattr(p, field, value)
    await session.commit()
    return ProductOut.from_model(p)


@router.delete("/products/{product_id}", status_code=204)
async def delete_product(product_id: int, request: Request, ctx: AdminDep, session: Session):
    # Заказы с этим товаром сохраняются: в order_items лежит снимок названия и цены
    p = await own_product(session, ctx.shop_id, product_id)
    paths = [i.path for i in p.images]
    await session.delete(p)
    await session.commit()
    for path in paths:
        media(request).delete(path)
    return Response(status_code=204)


# ── фото товара (до MAX_PRODUCT_IMAGES; первое — обложка) ──

@router.post("/products/{product_id}/images", response_model=ProductOut, status_code=201)
async def add_image(product_id: int, file: UploadFile, request: Request, ctx: AdminDep, session: Session):
    p = await own_product(session, ctx.shop_id, product_id)
    if len(p.images) >= MAX_PRODUCT_IMAGES:
        raise HTTPException(409, f"У товара уже {MAX_PRODUCT_IMAGES} фото — это максимум")
    data = await file.read(MAX_IMAGE_BYTES + 1)
    try:
        rel = media(request).save_product_image(ctx.shop_id, data)
    except MediaError as e:
        raise HTTPException(422, str(e)) from None
    position = max((i.position for i in p.images), default=-1) + 1
    p.images.append(ProductImage(path=rel, position=position))
    await session.commit()
    return ProductOut.from_model(await own_product(session, ctx.shop_id, product_id))


@router.delete("/products/{product_id}/images/{image_id}", response_model=ProductOut)
async def delete_image(product_id: int, image_id: int, request: Request, ctx: AdminDep, session: Session):
    p = await own_product(session, ctx.shop_id, product_id)
    img = next((i for i in p.images if i.id == image_id), None)
    if img is None:
        raise HTTPException(404, "Фото не найдено")
    path = img.path
    p.images.remove(img)
    await session.commit()
    media(request).delete(path)
    return ProductOut.from_model(await own_product(session, ctx.shop_id, product_id))


@router.put("/products/{product_id}/images/order", response_model=ProductOut)
async def reorder_images(product_id: int, body: ImageOrderIn, ctx: AdminDep, session: Session):
    """Новый порядок фото: передаётся полный список id; первое станет обложкой."""
    p = await own_product(session, ctx.shop_id, product_id)
    current = {i.id: i for i in p.images}
    if sorted(body.image_ids) != sorted(current):
        raise HTTPException(422, "Нужно передать все фото товара ровно по одному разу")
    for pos, image_id in enumerate(body.image_ids):
        current[image_id].position = pos
    await session.commit()
    return ProductOut.from_model(await own_product(session, ctx.shop_id, product_id))


# ── заказы ──

@router.get("/orders", response_model=list[AdminOrderOut])
async def list_orders(
    ctx: AdminDep,
    session: Session,
    status: OrderStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    stmt = (
        select(Order).where(Order.shop_id == ctx.shop_id)
        .options(selectinload(Order.items)).order_by(desc(Order.id)).limit(limit).offset(offset)
    )
    if status is not None:
        stmt = stmt.where(Order.status == status)
    return await session.scalars(stmt)


@router.patch("/orders/{order_id}", response_model=AdminOrderOut)
async def set_order_status(order_id: int, body: OrderStatusIn, ctx: AdminDep, session: Session):
    try:
        order, _old = await change_status(session, shop_id=ctx.shop_id, order_id=order_id, new=body.status)
    except OrderError as e:
        return order_error_response(e)
    # Уведомление покупателя о смене статуса — этап 7
    return order


# ── администраторы (только главный админ) ──

@router.get("/admins", response_model=list[AdminOut])
async def list_admins(ctx: MainAdminDep, session: Session):
    main = AdminOut(user_id=ctx.shop.admin_id, name=ctx.display_name, username=ctx.user.username, is_main=True)
    extra = [AdminOut.model_validate(a) for a in await admin_svc.list_admins(session, ctx.shop_id)]
    return [main, *extra]


@router.post("/admins", response_model=AdminOut, status_code=201)
async def add_admin(body: AdminAddIn, ctx: MainAdminDep, session: Session):
    try:
        admin = await admin_svc.add_admin(session, ctx.shop, user_id=body.user_id, added_by=ctx.user.id)
    except admin_svc.AdminError as e:
        raise HTTPException(e.status_code, e.message) from None
    return AdminOut.model_validate(admin)


@router.delete("/admins/{user_id}", status_code=204)
async def remove_admin(user_id: int, ctx: MainAdminDep, session: Session):
    try:
        await admin_svc.remove_admin(session, ctx.shop_id, user_id)
    except admin_svc.AdminError as e:
        raise HTTPException(e.status_code, e.message) from None
    return Response(status_code=204)


@router.post("/invites", response_model=InviteOut, status_code=201)
async def create_invite(ctx: MainAdminDep, session: Session):
    link, expires = await admin_svc.create_invite(session, ctx.shop, ctx.user.id)
    return InviteOut(link=link, expires_at=expires)
