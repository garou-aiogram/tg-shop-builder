"""Администраторы магазина.

Главный админ — shops.admin_id: его назначает и меняет только владелец в конструкторе.
Дополнительные — таблица shop_admins: их добавляет/удаляет только главный админ
(по Telegram ID или одноразовой ссылкой-приглашением). Права доп. админов в Mini App
такие же, как у главного, кроме управления админами.
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AdminInvite, Shop, ShopAdmin

INVITE_TTL = timedelta(hours=24)
INVITE_PREFIX = "adm_"  # deep link: t.me/<бот>?start=adm_<token>
MAX_EXTRA_ADMINS = 20


class AdminError(Exception):
    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class Roles:
    main_admin_id: int
    extra_admin_ids: frozenset[int]

    def is_admin(self, user_id: int | None) -> bool:
        return user_id is not None and (user_id == self.main_admin_id or user_id in self.extra_admin_ids)

    def is_main(self, user_id: int | None) -> bool:
        return user_id is not None and user_id == self.main_admin_id

    @property
    def all_ids(self) -> list[int]:
        return [self.main_admin_id, *sorted(self.extra_admin_ids - {self.main_admin_id})]


async def load_roles(session: AsyncSession, shop: Shop) -> Roles:
    ids = await session.scalars(select(ShopAdmin.user_id).where(ShopAdmin.shop_id == shop.id))
    return Roles(main_admin_id=shop.admin_id, extra_admin_ids=frozenset(ids))


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def list_admins(session: AsyncSession, shop_id: int) -> list[ShopAdmin]:
    return list(await session.scalars(
        select(ShopAdmin).where(ShopAdmin.shop_id == shop_id).order_by(ShopAdmin.created_at, ShopAdmin.id)
    ))


async def add_admin(
    session: AsyncSession, shop: Shop, *, user_id: int, added_by: int,
    name: str | None = None, username: str | None = None,
) -> ShopAdmin:
    if user_id == shop.admin_id:
        raise AdminError("Это главный администратор магазина")
    count = len(await list_admins(session, shop.id))
    if count >= MAX_EXTRA_ADMINS:
        raise AdminError(f"Максимум {MAX_EXTRA_ADMINS} дополнительных администраторов")
    admin = ShopAdmin(shop_id=shop.id, user_id=user_id, added_by=added_by, name=name, username=username)
    session.add(admin)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise AdminError("Этот пользователь уже администратор") from None
    return admin


async def remove_admin(session: AsyncSession, shop_id: int, user_id: int) -> None:
    res = await session.execute(delete(ShopAdmin).where(ShopAdmin.shop_id == shop_id, ShopAdmin.user_id == user_id))
    if res.rowcount == 0:
        raise AdminError("Администратор не найден", status_code=404)
    await session.commit()


async def touch_admin_profile(session: AsyncSession, shop_id: int, user_id: int, name: str, username: str | None) -> None:
    """Обновить имя/username доп. админа, если он открыл Mini App (для красивого списка).
    Пишем только при изменении, чтобы не делать UPDATE на каждый запрос."""
    await session.execute(
        update(ShopAdmin)
        .where(ShopAdmin.shop_id == shop_id, ShopAdmin.user_id == user_id)
        .where((ShopAdmin.name.is_distinct_from(name)) | (ShopAdmin.username.is_distinct_from(username)))
        .values(name=name, username=username)
    )
    await session.commit()


async def create_invite(session: AsyncSession, shop: Shop, created_by: int) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(18)  # 24 символа [A-Za-z0-9_-] — допустимо в start-параметре (≤64)
    expires = datetime.now(timezone.utc) + INVITE_TTL
    session.add(AdminInvite(shop_id=shop.id, token_hash=_hash(token), created_by=created_by, expires_at=expires))
    await session.commit()
    return f"https://t.me/{shop.bot_username}?start={INVITE_PREFIX}{token}", expires


async def redeem_invite(
    session: AsyncSession, shop: Shop, token: str, *, user_id: int, name: str, username: str | None,
) -> ShopAdmin:
    """Принять приглашение. Атомарно: UPDATE ... WHERE used_at IS NULL — одну ссылку
    не смогут использовать двое, даже открыв её одновременно."""
    now = datetime.now(timezone.utc)
    if user_id == shop.admin_id:
        raise AdminError("Вы уже главный администратор этого магазина")
    if user_id in (await load_roles(session, shop)).extra_admin_ids:
        raise AdminError("Вы уже администратор этого магазина")
    res = await session.execute(
        update(AdminInvite)
        .where(
            AdminInvite.shop_id == shop.id,
            AdminInvite.token_hash == _hash(token),
            AdminInvite.used_at.is_(None),
            AdminInvite.expires_at > now,
        )
        .values(used_at=now, used_by=user_id)
        .returning(AdminInvite.created_by)
    )
    created_by = res.scalar_one_or_none()
    if created_by is None:
        await session.rollback()
        raise AdminError("Ссылка-приглашение недействительна: уже использована или истекла")
    # Если главный админ сменился после выдачи ссылки — приглашение от прежнего не действует
    if created_by != shop.admin_id:
        await session.rollback()
        raise AdminError("Ссылка-приглашение больше не действует")
    return await add_admin(session, shop, user_id=user_id, added_by=created_by, name=name, username=username)
