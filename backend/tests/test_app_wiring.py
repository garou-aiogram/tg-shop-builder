"""Этап 4: настоящее приложение из app.main собирает API и раздаёт /media."""
from cryptography.fernet import Fernet

from app.config import load_settings
from app.main import create_app
from app.services.media import MediaStorage
from tests.api_helpers import auth, client, make_shop
from tests.conftest import TOKEN_A

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


async def test_real_app_serves_api_and_media(sessionmaker, cipher, tmp_path):
    settings = load_settings({
        "BUILDER_BOT_TOKEN": "1:x", "PUBLIC_URL": "https://x.example", "WEBHOOK_SECRET": "s",
        "DATABASE_URL": "postgresql+asyncpg://u:p@h/db", "FERNET_KEY": Fernet.generate_key().decode(),
        "MEDIA_DIR": str(tmp_path),
    })
    app = create_app(settings)
    # lifespan (Telegram) не запускаем — подставляем состояние сами
    app.state.sessionmaker, app.state.cipher, app.state.media = sessionmaker, cipher, MediaStorage(tmp_path)

    shop = await make_shop(sessionmaker, cipher, token=TOKEN_A, admin_id=1, name="Alpha")
    async with client(app) as c:
        r = await c.post(f"/api/shops/{shop.id}/admin/products", json={"name": "Чай", "price": "10"},
                         headers=auth(TOKEN_A, 1))
        pid = r.json()["id"]
        r = await c.post(f"/api/shops/{shop.id}/admin/products/{pid}/images",
                         files={"file": ("a.png", PNG)}, headers=auth(TOKEN_A, 1))
        img = await c.get(r.json()["image_url"])
        assert img.status_code == 200 and img.content == PNG and img.headers["content-type"] == "image/png"
        assert (await c.get("/media/../../etc/passwd")).status_code == 404
        assert (await c.get("/api/health")).json() == {"status": "ok"}
