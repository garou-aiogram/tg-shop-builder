"""Зависимости API: сессия БД и контекст запроса (магазин + пользователь + роль).

Каждый запрос Mini App несёт заголовок `Authorization: tma <initData>`.
initData проверяется токеном ИМЕННО того магазина, чей shop_id в URL.
Роль вычисляется здесь, на сервере: главный админ — shops.admin_id,
дополнительные — таблица shop_admins. Клиент не может «объявить себя админом» —
никаких флагов с фронта не читаем.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Path, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Shop
from app.security.crypto import TokenCipher, TokenDecryptError
from app.security.init_data import InitDataError, WebAppUser, validate_init_data
from app.services.admins import Roles, load_roles, touch_admin_profile

log = logging.getLogger(__name__)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


Session = Annotated[AsyncSession, Depends(get_session)]


@dataclass(frozen=True)
class Ctx:
    shop: Shop
    user: WebAppUser
    roles: Roles

    @property
    def is_admin(self) -> bool:
        return self.roles.is_admin(self.user.id)

    @property
    def is_main_admin(self) -> bool:
        return self.roles.is_main(self.user.id)

    @property
    def display_name(self) -> str:
        return " ".join(filter(None, [self.user.first_name, self.user.last_name]))

    @property
    def shop_id(self) -> int:
        return self.shop.id


async def get_ctx(
    request: Request,
    session: Session,
    shop_id: Annotated[int, Path(ge=1)],
    authorization: Annotated[str | None, Header()] = None,
) -> Ctx:
    if not authorization or not authorization.startswith("tma "):
        raise HTTPException(401, "Нет данных авторизации Telegram")

    shop = await session.scalar(select(Shop).where(Shop.id == shop_id))
    if shop is None or not shop.is_active:
        raise HTTPException(404, "Магазин не найден или выключен")

    cipher: TokenCipher = request.app.state.cipher
    try:
        token = cipher.decrypt(shop.bot_token_encrypted)
    except TokenDecryptError:
        log.error("shop %s: cannot decrypt token", shop.id)
        raise HTTPException(503, "Магазин временно недоступен") from None

    try:
        user = validate_init_data(authorization[4:], token)
    except InitDataError as e:
        log.info("shop %s: initData rejected (%s)", shop.id, e)
        raise HTTPException(401, "Недействительные данные авторизации Telegram") from None

    roles = await load_roles(session, shop)
    ctx = Ctx(shop=shop, user=user, roles=roles)
    if user.id in roles.extra_admin_ids:
        await touch_admin_profile(session, shop.id, user.id, ctx.display_name, user.username)
    return ctx


CtxDep = Annotated[Ctx, Depends(get_ctx)]


async def require_admin(ctx: CtxDep) -> Ctx:
    if not ctx.is_admin:
        raise HTTPException(403, "Доступно только администратору магазина")
    return ctx


AdminDep = Annotated[Ctx, Depends(require_admin)]


async def require_main_admin(ctx: CtxDep) -> Ctx:
    if not ctx.is_main_admin:
        raise HTTPException(403, "Доступно только главному администратору")
    return ctx


MainAdminDep = Annotated[Ctx, Depends(require_main_admin)]
