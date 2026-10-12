"""Pydantic-схемы API. Деньги — Decimal, в JSON уходят строкой ("199.90"):
float для денег не используем, чтобы не было ошибок округления."""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator, model_validator

from app.db.models import DeliveryMethod, OrderStatus, PaymentMethod

# Деньги в ответах — всегда строка с двумя знаками: "80.00", а не "80" / "80.0"
MoneyOut = Annotated[Decimal, PlainSerializer(lambda d: f"{d:.2f}", return_type=str, when_used="json")]
Price = Annotated[Decimal, Field(ge=0, le=Decimal("9999999999.99"), max_digits=12, decimal_places=2)]
Name = Annotated[str, Field(min_length=1, max_length=128)]


def _clean(v: str) -> str:
    return " ".join(v.split())


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ── магазин / пользователь ──

class ShopOut(BaseModel):
    id: int
    name: str
    bot_username: str


class MeOut(BaseModel):
    user_id: int
    first_name: str
    is_admin: bool
    is_main_admin: bool
    shop: ShopOut


# ── категории ──

class CategoryOut(ORM):
    id: int
    name: str
    sort_order: int


class CategoryIn(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=64)]
    sort_order: int = 0

    _n = field_validator("name")(lambda cls, v: _clean(v))


class CategoryPatch(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=64)] | None = None
    sort_order: int | None = None

    _n = field_validator("name")(lambda cls, v: _clean(v) if v is not None else v)


# ── товары ──

class ImageOut(BaseModel):
    id: int
    url: str


class ProductOut(ORM):
    id: int
    category_id: int | None
    name: str
    description: str
    price: MoneyOut
    old_price: MoneyOut | None
    image_url: str | None  # обложка (первое фото) — для карточек каталога и корзины
    images: list[ImageOut]  # все фото по порядку, первое — обложка
    in_stock: bool

    @classmethod
    def from_model(cls, p) -> "ProductOut":
        images = [ImageOut(id=i.id, url=f"/media/{i.path}") for i in p.images]
        return cls(
            id=p.id, category_id=p.category_id, name=p.name, description=p.description,
            price=p.price, old_price=p.old_price, in_stock=p.in_stock,
            image_url=images[0].url if images else None, images=images,
        )


class ImageOrderIn(BaseModel):
    image_ids: list[int] = Field(max_length=10)


class _ProductFields(BaseModel):
    @model_validator(mode="after")
    def _old_price_gt_price(self):
        price, old = getattr(self, "price", None), getattr(self, "old_price", None)
        if price is not None and old is not None and old <= price:
            raise ValueError("Старая цена должна быть больше текущей")
        return self


class ProductIn(_ProductFields):
    name: Name
    description: Annotated[str, Field(max_length=4000)] = ""
    price: Price
    old_price: Price | None = None
    category_id: int | None = None
    in_stock: bool = True

    _n = field_validator("name")(lambda cls, v: _clean(v))


class ProductPatch(_ProductFields):
    # Передаются только изменяемые поля; явный null у old_price/category_id — сбросить значение
    name: Name | None = None
    description: Annotated[str, Field(max_length=4000)] | None = None
    price: Price | None = None
    old_price: Price | None = None
    category_id: int | None = None
    in_stock: bool | None = None

    _n = field_validator("name")(lambda cls, v: _clean(v) if v is not None else v)


ProductSort = Literal["new", "price_asc", "price_desc", "discount"]


# ── корзина ──

class CartItemOut(BaseModel):
    product: ProductOut
    quantity: int
    subtotal: MoneyOut


class CartOut(BaseModel):
    items: list[CartItemOut]
    total: MoneyOut
    count: int


class CartQuantityIn(BaseModel):
    quantity: Annotated[int, Field(ge=0, le=999)]  # 0 — убрать из корзины


# ── заказы ──

PHONE_RE = re.compile(r"^\+?[\d\s()\-]{5,25}$")


class OrderIn(BaseModel):
    customer_name: Name
    phone: Annotated[str, Field(max_length=32)]
    delivery_method: DeliveryMethod
    address: Annotated[str, Field(max_length=500)] | None = None
    comment: Annotated[str, Field(max_length=1000)] = ""

    _n = field_validator("customer_name")(lambda cls, v: _clean(v))

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        v = v.strip()
        digits = sum(c.isdigit() for c in v)
        if not PHONE_RE.match(v) or not 5 <= digits <= 15:
            raise ValueError("Некорректный номер телефона")
        return v

    @model_validator(mode="after")
    def _address_for_delivery(self):
        if self.address is not None:
            self.address = self.address.strip() or None
        if self.delivery_method is DeliveryMethod.DELIVERY and not self.address:
            raise ValueError("Для доставки укажите адрес")
        if self.delivery_method is DeliveryMethod.PICKUP:
            self.address = None
        return self


class OrderItemOut(ORM):
    product_id: int | None
    product_name: str
    price: MoneyOut
    quantity: int


class OrderOut(ORM):
    id: int
    status: OrderStatus
    payment_method: PaymentMethod
    customer_name: str
    phone: str
    delivery_method: DeliveryMethod
    address: str | None
    comment: str
    total: MoneyOut
    created_at: datetime
    items: list[OrderItemOut]


class AdminOrderOut(OrderOut):
    # Контакты покупателя для админа. tg_* — из подписанного initData на момент заказа
    user_id: int
    tg_username: str | None
    tg_name: str | None


# ── администраторы ──

class AdminOut(ORM):
    user_id: int
    name: str | None
    username: str | None
    is_main: bool = False


class AdminAddIn(BaseModel):
    user_id: Annotated[int, Field(gt=0, lt=2**52)]


class InviteOut(BaseModel):
    link: str
    expires_at: datetime


class OrderStatusIn(BaseModel):
    status: OrderStatus
