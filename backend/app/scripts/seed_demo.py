"""Демо-товары для проверки витрины до появления админки (этап 6).

Запуск на сервере:
    docker compose exec backend python -m app.scripts.seed_demo --shop 1

Ничего не удаляет. Если в магазине уже есть товары — ничего не делает
(повторный запуск безопасен). Потом демо-товары удаляются в админке.
"""
from __future__ import annotations

import argparse
import asyncio
import os
from decimal import Decimal

from sqlalchemy import func, select

from app.db.models import Category, Product, Shop
from app.db.session import make_engine, make_sessionmaker

D = Decimal
DEMO = {
    "Чай": [
        ("Сенча", "Японский зелёный чай с травянистым вкусом. 100 г.", D("450"), D("590"), True),
        ("Молочный улун", "Китайский улун со сливочным ароматом. 100 г.", D("620"), None, True),
        ("Эрл Грей", "Чёрный чай с бергамотом. 100 г.", D("390"), None, True),
        ("Пуэр шу", "Выдержанный пуэр, прессованный блин 357 г.", D("1890"), D("2400"), False),
    ],
    "Кофе": [
        ("Эфиопия Иргачефф", "Светлая обжарка, ноты цитруса и жасмина. 250 г.", D("990"), None, True),
        ("Бразилия Сантос", "Средняя обжарка, шоколад и орех. 250 г.", D("790"), D("890"), True),
    ],
    "Сладости": [
        ("Пахлава", "Ореховая, с мёдом. 300 г.", D("540"), None, True),
        ("Макарон, набор 6 шт.", "Ассорти вкусов.", D("480"), None, True),
    ],
}


async def seed(shop_id: int) -> None:
    engine = make_engine(os.environ["DATABASE_URL"])
    try:
        async with make_sessionmaker(engine)() as s:
            shop = await s.get(Shop, shop_id)
            if shop is None:
                print(f"Магазин {shop_id} не найден")
                return
            existing = await s.scalar(select(func.count(Product.id)).where(Product.shop_id == shop_id))
            if existing:
                print(f"В магазине «{shop.name}» уже есть товары ({existing}) — ничего не добавляю")
                return
            n = 0
            for order, (cat_name, items) in enumerate(DEMO.items()):
                cat = Category(shop_id=shop_id, name=cat_name, sort_order=order)
                s.add(cat)
                await s.flush()
                for name, desc, price, old, in_stock in items:
                    s.add(Product(shop_id=shop_id, category_id=cat.id, name=name, description=desc,
                                  price=price, old_price=old, in_stock=in_stock))
                    n += 1
            await s.commit()
            print(f"Магазин «{shop.name}»: добавлено {len(DEMO)} категории и {n} товаров")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shop", type=int, required=True, help="ID магазина")
    asyncio.run(seed(parser.parse_args().shop))


if __name__ == "__main__":
    main()
