"""Модели БД.

Мультитенантность: всё, что принадлежит магазину, несёт shop_id
и удаляется каскадно вместе с магазином.
Деньги — Numeric(12, 2) (рубли с копейками), без float.
"""
from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

MAX_PRODUCT_IMAGES = 10

Money = Numeric(12, 2)


class OrderStatus(str, enum.Enum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"

    @classmethod
    def active(cls) -> tuple[OrderStatus, ...]:
        return (cls.NEW, cls.IN_PROGRESS)

    @classmethod
    def finished(cls) -> tuple[OrderStatus, ...]:
        return (cls.DONE, cls.CANCELLED)


class PaymentMethod(str, enum.Enum):
    # Сейчас только ручной расчёт. Модуль оплаты позже добавит сюда
    # значения (например "yookassa", "telegram_stars") новой миграцией.
    MANUAL = "manual"


class DeliveryMethod(str, enum.Enum):
    PICKUP = "pickup"
    DELIVERY = "delivery"


def _str_enum(enum_cls: type[enum.Enum], name: str) -> Enum:
    # VARCHAR + CHECK вместо нативного PG ENUM: новые значения добавляются
    # простой заменой CHECK-констрейнта, без ALTER TYPE.
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )


class Shop(TimestampMixin, Base):
    __tablename__ = "shops"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Кто создал магазин в конструкторе — только он управляет им в главном боте
    owner_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    # Администратор магазина (управляет товарами/заказами в Mini App)
    admin_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)

    # Токен хранится ТОЛЬКО зашифрованным (Fernet). Открытого токена в БД нет.
    bot_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    # id бота из getMe — уникален: один бот не может обслуживать два магазина,
    # даже если его токен перевыпустили в BotFather.
    bot_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    bot_username: Mapped[str] = mapped_column(String(64), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)

    categories: Mapped[list[Category]] = relationship(back_populates="shop", cascade="all, delete-orphan", passive_deletes=True)
    products: Mapped[list[Product]] = relationship(back_populates="shop", cascade="all, delete-orphan", passive_deletes=True)

    def __repr__(self) -> str:  # без токена в repr — он может попасть в логи
        return f"<Shop id={self.id} bot=@{self.bot_username} active={self.is_active}>"


class Category(TimestampMixin, Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("shop_id", "name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    shop: Mapped[Shop] = relationship(back_populates="categories")
    products: Mapped[list[Product]] = relationship(back_populates="category", passive_deletes=True)


class Product(TimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("price >= 0", name="price_non_negative"),
        CheckConstraint("old_price IS NULL OR old_price >= 0", name="old_price_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), index=True, nullable=False)
    # Удаление категории не удаляет товары — они становятся «без категории»
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), index=True, nullable=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", server_default="", nullable=False)
    price: Mapped[Decimal] = mapped_column(Money, nullable=False)
    old_price: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    in_stock: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)

    shop: Mapped[Shop] = relationship(back_populates="products")
    category: Mapped[Category | None] = relationship(back_populates="products")
    # Первое по position — обложка в каталоге
    images: Mapped[list[ProductImage]] = relationship(
        back_populates="product", cascade="all, delete-orphan", passive_deletes=True,
        order_by="ProductImage.position, ProductImage.id",
    )

    @property
    def cover_path(self) -> str | None:
        return self.images[0].path if self.images else None


class ProductImage(Base):
    __tablename__ = "product_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True, nullable=False)
    # Путь относительно MEDIA_DIR, напр. "shops/3/ab12cd.jpg"
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    product: Mapped[Product] = relationship(back_populates="images")


class CartItem(TimestampMixin, Base):
    """Корзина хранится на сервере: (shop, user) → набор позиций."""

    __tablename__ = "cart_items"
    __table_args__ = (
        UniqueConstraint("shop_id", "user_id", "product_id"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    product: Mapped[Product] = relationship()


class Order(TimestampMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("total >= 0", name="total_non_negative"),
        CheckConstraint("delivery_method <> 'delivery' OR address IS NOT NULL", name="address_for_delivery"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)

    customer_name: Mapped[str] = mapped_column(String(128), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    # Из ПОДПИСАННОГО initData на момент заказа — покупатель не может подставить чужие.
    # username у многих пользователей Telegram отсутствует — поле nullable.
    tg_username: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tg_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    delivery_method: Mapped[DeliveryMethod] = mapped_column(_str_enum(DeliveryMethod, "delivery_method"), nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    comment: Mapped[str] = mapped_column(Text, default="", server_default="", nullable=False)

    total: Mapped[Decimal] = mapped_column(Money, nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        _str_enum(OrderStatus, "order_status"), default=OrderStatus.NEW, server_default=OrderStatus.NEW.value, nullable=False
    )
    # Точка расширения под оплату: пока всегда "manual"
    payment_method: Mapped[PaymentMethod] = mapped_column(
        _str_enum(PaymentMethod, "payment_method"),
        default=PaymentMethod.MANUAL,
        server_default=PaymentMethod.MANUAL.value,
        nullable=False,
    )

    items: Mapped[list[OrderItem]] = relationship(back_populates="order", cascade="all, delete-orphan", passive_deletes=True)


class OrderItem(Base):
    """Снимок позиции на момент заказа: если товар потом изменят или удалят,
    заказ сохранит исходные название и цену."""

    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("price >= 0", name="price_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True, nullable=False)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    product_name: Mapped[str] = mapped_column(String(128), nullable=False)
    price: Mapped[Decimal] = mapped_column(Money, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    order: Mapped[Order] = relationship(back_populates="items")


class ShopAdmin(Base):
    """Дополнительные администраторы. Главный админ — shops.admin_id (назначает владелец
    в конструкторе); дополнительных добавляет и удаляет только главный."""

    __tablename__ = "shop_admins"
    __table_args__ = (UniqueConstraint("shop_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Для показа в списке; известны, если человек пришёл по приглашению или открывал Mini App
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    username: Mapped[str | None] = mapped_column(String(32), nullable=True)
    added_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AdminInvite(Base):
    """Одноразовое приглашение в админы: ссылка t.me/<бот>?start=adm_<token>.
    В БД — только SHA-256 токена: утечка БД не даёт рабочих ссылок."""

    __tablename__ = "admin_invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    used_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
