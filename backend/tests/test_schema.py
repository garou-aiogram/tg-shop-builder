"""Этап 1: миграции и инварианты схемы."""
from decimal import Decimal

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, StatementError

from app.db.base import Base
from app.db.models import (
    CartItem, Category, DeliveryMethod, Order, OrderItem, OrderStatus, PaymentMethod, Product, Shop,
)
from tests.conftest import alembic_cfg


async def test_migrations_match_models(engine):
    """Миграция 0001 создаёт ровно то, что описано в моделях."""
    async with engine.connect() as conn:
        diff = await conn.run_sync(
            lambda c: compare_metadata(MigrationContext.configure(c, opts={"compare_type": True}), Base.metadata)
        )
    assert diff == []


def test_downgrade_and_upgrade_again(migrated_db):
    cfg = alembic_cfg()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


def make_shop(**kw) -> Shop:
    data = dict(owner_id=1, admin_id=2, name="Shop", bot_token_encrypted="gAAAA-fake", bot_id=100, bot_username="test_bot")
    data.update(kw)
    return Shop(**data)


async def test_bot_id_is_unique(session):
    session.add(make_shop(bot_id=555))
    await session.flush()
    session.add(make_shop(bot_id=555, owner_id=99))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_shop_defaults(session):
    shop = make_shop()
    session.add(shop)
    await session.flush()
    await session.refresh(shop)
    assert shop.is_active is True
    assert shop.created_at is not None
    assert "fake" not in repr(shop)  # токен не утекает через repr


async def test_order_defaults_and_payment_extension_point(session):
    shop = make_shop()
    session.add(shop)
    await session.flush()
    order = Order(shop_id=shop.id, user_id=10, customer_name="Иван", phone="+79990000000",
                  delivery_method=DeliveryMethod.PICKUP, total=Decimal("100.00"))
    order.items.append(OrderItem(product_name="Чай", price=Decimal("50.00"), quantity=2))
    session.add(order)
    await session.flush()
    await session.refresh(order)
    assert order.status is OrderStatus.NEW
    assert order.payment_method is PaymentMethod.MANUAL


async def test_delivery_requires_address(session):
    shop = make_shop()
    session.add(shop)
    await session.flush()
    session.add(Order(shop_id=shop.id, user_id=10, customer_name="A", phone="1",
                      delivery_method=DeliveryMethod.DELIVERY, address=None, total=Decimal(0)))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_unknown_status_rejected(session):
    shop = make_shop()
    session.add(shop)
    await session.flush()
    session.add(Order(shop_id=shop.id, user_id=1, customer_name="A", phone="1",
                      delivery_method=DeliveryMethod.PICKUP, total=Decimal(0), status="paid"))
    with pytest.raises(StatementError):
        await session.flush()


async def test_negative_price_rejected(session):
    shop = make_shop()
    session.add(shop)
    await session.flush()
    session.add(Product(shop_id=shop.id, name="X", price=Decimal("-1")))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_category_delete_keeps_products(session):
    shop = make_shop()
    session.add(shop)
    await session.flush()
    cat = Category(shop_id=shop.id, name="Напитки")
    session.add(cat)
    await session.flush()
    p = Product(shop_id=shop.id, category_id=cat.id, name="Сок", price=Decimal("99.90"))
    session.add(p)
    await session.flush()
    product_id = p.id
    await session.delete(cat)
    await session.flush()
    session.expire_all()
    p = await session.scalar(select(Product).where(Product.id == product_id))
    assert p is not None and p.category_id is None


async def test_shop_delete_cascades(session):
    shop = make_shop()
    session.add(shop)
    await session.flush()
    p = Product(shop_id=shop.id, name="Сок", price=Decimal("10"))
    session.add(p)
    await session.flush()
    session.add(CartItem(shop_id=shop.id, user_id=5, product_id=p.id, quantity=1))
    await session.flush()
    await session.delete(shop)
    await session.flush()
    assert (await session.scalar(select(CartItem).where(CartItem.shop_id == shop.id))) is None
    assert (await session.scalar(select(Product).where(Product.shop_id == shop.id))) is None


async def test_cart_item_unique_per_user_product(session):
    shop = make_shop()
    session.add(shop)
    await session.flush()
    p = Product(shop_id=shop.id, name="Сок", price=Decimal("10"))
    session.add(p)
    await session.flush()
    session.add_all([CartItem(shop_id=shop.id, user_id=5, product_id=p.id, quantity=1),
                     CartItem(shop_id=shop.id, user_id=5, product_id=p.id, quantity=2)])
    with pytest.raises(IntegrityError):
        await session.flush()
