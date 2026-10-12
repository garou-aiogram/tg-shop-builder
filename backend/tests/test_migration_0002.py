"""Миграция 0002 переносит существующие фото из products.image_path в product_images.

Тест синхронный: alembic/env.py сам вызывает asyncio.run(), поэтому из async-теста его не запустить.
"""
import asyncio

from alembic import command
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.conftest import TEST_DB_URL, alembic_cfg


def sql(query: str):
    async def run():
        eng = create_async_engine(TEST_DB_URL)
        try:
            async with eng.begin() as conn:
                res = await conn.execute(text(query))
                return res.fetchall() if res.returns_rows else None
        finally:
            await eng.dispose()
    return asyncio.run(run())


def test_0002_moves_images_and_downgrade_restores_cover(migrated_db):
    cfg = alembic_cfg()
    command.downgrade(cfg, "0001")
    sql("INSERT INTO shops (id, owner_id, admin_id, name, bot_token_encrypted, bot_id, bot_username) "
        "VALUES (90, 1, 1, 'M', 'x', 9090, 'm_bot')")
    sql("INSERT INTO products (id, shop_id, name, price, image_path) VALUES "
        "(901, 90, 'with', 1, 'shops/90/a.jpg'), (902, 90, 'without', 1, NULL)")

    command.upgrade(cfg, "head")
    assert sql("SELECT product_id, path, position FROM product_images ORDER BY product_id") == [(901, "shops/90/a.jpg", 0)]

    # откат возвращает обложку (первое по position) в старую колонку
    sql("INSERT INTO product_images (product_id, path, position) VALUES (901, 'shops/90/b.jpg', 1)")
    command.downgrade(cfg, "0001")
    assert sql("SELECT id, image_path FROM products ORDER BY id") == [(901, "shops/90/a.jpg"), (902, None)]

    sql("DELETE FROM shops WHERE id = 90")
    command.upgrade(cfg, "head")
