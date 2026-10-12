"""Сборка приложения API для тестов: без lifespan (никакого Telegram), state задаётся вручную."""
import json
import time

import httpx
from fastapi import FastAPI

from app.api import admin, public
from app.db.models import Shop
from app.security.init_data import sign_init_data
from app.services.media import MediaStorage


def build_api_app(sessionmaker, cipher, media_dir) -> FastAPI:
    app = FastAPI()
    app.state.sessionmaker = sessionmaker
    app.state.cipher = cipher
    app.state.media = MediaStorage(media_dir)
    app.include_router(public.router)
    app.include_router(admin.router)
    return app


def client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def auth(token: str, user_id: int, first_name: str = "U", username: str | None = None) -> dict[str, str]:
    user = {"id": user_id, "first_name": first_name, **({"username": username} if username else {})}
    raw = sign_init_data({"user": json.dumps(user), "auth_date": str(int(time.time()))}, token)
    return {"Authorization": f"tma {raw}"}


async def make_shop(sessionmaker, cipher, *, token: str, admin_id: int, name: str = "Shop", active=True) -> Shop:
    async with sessionmaker() as s:
        shop = Shop(owner_id=1, admin_id=admin_id, name=name, bot_token_encrypted=cipher.encrypt(token),
                    bot_id=int(token.split(":")[0]), bot_username=f"{name.lower()}_bot", is_active=active)
        s.add(shop)
        await s.commit()
        return shop
