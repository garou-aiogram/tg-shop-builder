from sqlalchemy import func, select

from app.db.models import Category, Product
from app.scripts.seed_demo import seed
from tests.api_helpers import make_shop
from tests.conftest import TEST_DB_URL, TOKEN_A


async def test_seed_is_idempotent(sessionmaker, cipher, monkeypatch, capsys):
    shop = await make_shop(sessionmaker, cipher, token=TOKEN_A, admin_id=1, name="Alpha")
    monkeypatch.setenv("DATABASE_URL", TEST_DB_URL)
    await seed(shop.id)
    await seed(shop.id)  # повторный запуск ничего не дублирует
    async with sessionmaker() as s:
        assert await s.scalar(select(func.count(Product.id))) == 8
        assert await s.scalar(select(func.count(Category.id))) == 3
    assert "уже есть товары" in capsys.readouterr().out
