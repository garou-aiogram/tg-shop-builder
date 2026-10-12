"""Этап 4: REST API — авторизация, роль admin, каталог, корзина, заказы, изоляция магазинов."""
import pytest

from tests.api_helpers import auth, build_api_app, client, make_shop
from tests.conftest import TOKEN_A, TOKEN_B

ADMIN, BUYER, BUYER2 = 100, 200, 300
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


@pytest.fixture
async def env(sessionmaker, cipher, tmp_path):
    shop = await make_shop(sessionmaker, cipher, token=TOKEN_A, admin_id=ADMIN, name="Alpha")
    other = await make_shop(sessionmaker, cipher, token=TOKEN_B, admin_id=ADMIN, name="Beta")
    app = build_api_app(sessionmaker, cipher, tmp_path)
    async with client(app) as c:
        yield c, shop, other, tmp_path


def url(shop, path=""):
    return f"/api/shops/{shop.id}{path}"


A = lambda uid=ADMIN: auth(TOKEN_A, uid)  # noqa: E731 — initData, подписанный ботом магазина Alpha


async def add_product(c, shop, **kw):
    body = {"name": "Чай", "price": "100.00", **kw}
    r = await c.post(url(shop, "/admin/products"), json=body, headers=A())
    assert r.status_code == 201, r.text
    return r.json()


# ── авторизация ──

async def test_no_auth_header(env):
    c, shop, *_ = env
    assert (await c.get(url(shop, "/me"))).status_code == 401


async def test_forged_init_data(env):
    c, shop, *_ = env
    r = await c.get(url(shop, "/me"), headers={"Authorization": "tma user=%7B%22id%22%3A1%7D&auth_date=1&hash=abc"})
    assert r.status_code == 401


async def test_init_data_of_other_shop_rejected(env):
    # Пользователь подписан ботом Beta, а стучится в Alpha
    c, shop, *_ = env
    r = await c.get(url(shop, "/me"), headers=auth(TOKEN_B, BUYER))
    assert r.status_code == 401


async def test_inactive_or_missing_shop(env, sessionmaker, cipher):
    c, *_ = env
    off = await make_shop(sessionmaker, cipher, token="333333333:" + "C" * 35, admin_id=ADMIN, name="Off", active=False)
    assert (await c.get(f"/api/shops/{off.id}/me", headers=auth("333333333:" + "C" * 35, BUYER))).status_code == 404
    assert (await c.get("/api/shops/9999/me", headers=A())).status_code == 404


# ── роль admin ──

async def test_me_reports_role(env):
    c, shop, *_ = env
    admin = (await c.get(url(shop, "/me"), headers=A(ADMIN))).json()
    buyer = (await c.get(url(shop, "/me"), headers=A(BUYER))).json()
    assert admin["is_admin"] is True and buyer["is_admin"] is False
    assert admin["shop"] == {"id": shop.id, "name": "Alpha", "bot_username": "alpha_bot"}


async def test_buyer_cannot_use_admin_api(env):
    c, shop, *_ = env
    p = await add_product(c, shop)
    h = A(BUYER)
    assert (await c.post(url(shop, "/admin/products"), json={"name": "x", "price": "1"}, headers=h)).status_code == 403
    assert (await c.patch(url(shop, f"/admin/products/{p['id']}"), json={"price": "1"}, headers=h)).status_code == 403
    assert (await c.delete(url(shop, f"/admin/products/{p['id']}"), headers=h)).status_code == 403
    assert (await c.post(url(shop, "/admin/categories"), json={"name": "x"}, headers=h)).status_code == 403
    assert (await c.get(url(shop, "/admin/orders"), headers=h)).status_code == 403


async def test_admin_role_ignores_client_claims(env):
    # Никакие поля в initData/запросе не делают покупателя админом
    c, shop, *_ = env
    h = auth(TOKEN_A, BUYER)
    r = await c.post(url(shop, "/admin/categories?is_admin=true"), json={"name": "x", "is_admin": True}, headers=h)
    assert r.status_code == 403


async def test_admin_of_one_shop_is_buyer_in_another(env, sessionmaker, cipher):
    c, shop, other, _ = env
    third_token = "444444444:" + "D" * 35
    third = await make_shop(sessionmaker, cipher, token=third_token, admin_id=999, name="Gamma")
    r = await c.post(f"/api/shops/{third.id}/admin/categories", json={"name": "x"}, headers=auth(third_token, ADMIN))
    assert r.status_code == 403


# ── каталог ──

async def test_catalog_search_filter_sort(env):
    c, shop, *_ = env
    cat = (await c.post(url(shop, "/admin/categories"), json={"name": "Напитки"}, headers=A())).json()
    await add_product(c, shop, name="Зелёный чай", price="300", old_price="400", category_id=cat["id"])  # -25%
    await add_product(c, shop, name="Чёрный чай", price="100", category_id=cat["id"])
    await add_product(c, shop, name="Кофе 100%_arabica", price="500", old_price="1000")                 # -50%
    await add_product(c, shop, name="Какао", price="50", in_stock=False)

    get = lambda **q: c.get(url(shop, "/products"), params=q, headers=A(BUYER))  # noqa: E731
    names = lambda r: [p["name"] for p in r.json()]  # noqa: E731

    assert names(await get(sort="price_asc")) == ["Чёрный чай", "Зелёный чай", "Кофе 100%_arabica", "Какао"]
    assert names(await get(sort="price_desc"))[0] == "Кофе 100%_arabica"
    assert names(await get(sort="discount"))[:2] == ["Кофе 100%_arabica", "Зелёный чай"]
    assert names(await get(q="чай")) == ["Чёрный чай", "Зелёный чай"]
    assert names(await get(q="100%")) == ["Кофе 100%_arabica"]  # % экранирован, а не wildcard
    assert names(await get(q="_")) == ["Кофе 100%_arabica"]
    assert set(names(await get(category_id=cat["id"]))) == {"Зелёный чай", "Чёрный чай"}
    assert names(await get())[-1] == "Какао"  # нет в наличии — в конце списка

    p = (await get(q="Зелёный")).json()[0]
    assert p["price"] == "300.00" and p["old_price"] == "400.00"  # деньги строкой, без float


async def test_catalog_isolated_between_shops(env):
    c, shop, other, _ = env
    p = await add_product(c, shop, name="Секрет Alpha")
    hb = auth(TOKEN_B, BUYER)
    assert (await c.get(url(other, "/products"), headers=hb)).json() == []
    assert (await c.get(url(other, f"/products/{p['id']}"), headers=hb)).status_code == 404
    # и через URL своего магазина чужой товар в корзину не положить
    assert (await c.put(url(other, f"/cart/items/{p['id']}"), json={"quantity": 1}, headers=hb)).status_code == 404


async def test_product_validation(env):
    c, shop, *_ = env
    bad = [
        {"name": "", "price": "1"},
        {"name": "x", "price": "-1"},
        {"name": "x", "price": "1.234"},
        {"name": "x", "price": "100", "old_price": "90"},  # старая цена меньше новой
    ]
    for body in bad:
        assert (await c.post(url(shop, "/admin/products"), json=body, headers=A())).status_code == 422, body


async def test_cannot_use_foreign_category(env):
    c, shop, other, _ = env
    foreign = (await c.post(url(other, "/admin/categories"), json={"name": "B"}, headers=auth(TOKEN_B, ADMIN))).json()
    r = await c.post(url(shop, "/admin/products"), json={"name": "x", "price": "1", "category_id": foreign["id"]}, headers=A())
    assert r.status_code == 404


async def test_admin_crud(env):
    c, shop, *_ = env
    cat = (await c.post(url(shop, "/admin/categories"), json={"name": "  Чай  "}, headers=A())).json()
    assert cat["name"] == "Чай"
    assert (await c.post(url(shop, "/admin/categories"), json={"name": "Чай"}, headers=A())).status_code == 409

    p = await add_product(c, shop, category_id=cat["id"])
    r = await c.patch(url(shop, f"/admin/products/{p['id']}"), json={"price": "80", "old_price": "100"}, headers=A())
    assert r.json()["price"] == "80.00" and r.json()["old_price"] == "100.00"
    r = await c.patch(url(shop, f"/admin/products/{p['id']}"), json={"old_price": None}, headers=A())
    assert r.json()["old_price"] is None

    # удаление категории: товар остаётся без категории
    assert (await c.delete(url(shop, f"/admin/categories/{cat['id']}"), headers=A())).status_code == 204
    assert (await c.get(url(shop, f"/products/{p['id']}"), headers=A())).json()["category_id"] is None

    assert (await c.delete(url(shop, f"/admin/products/{p['id']}"), headers=A())).status_code == 204
    assert (await c.get(url(shop, f"/products/{p['id']}"), headers=A())).status_code == 404


# ── фото (до 10, первое — обложка) ──

def img_path(media_dir, url):
    return media_dir / url.removeprefix("/media/")


async def upload(c, shop, pid, data, name="a.png", h=None):
    return await c.post(url(shop, f"/admin/products/{pid}/images"), files={"file": (name, data)}, headers=h or A())


async def test_multiple_images_cover_reorder_delete(env):
    c, shop, _, media_dir = env
    p = await add_product(c, shop)
    assert p["images"] == [] and p["image_url"] is None

    r1 = (await upload(c, shop, p["id"], PNG)).json()
    r2 = (await upload(c, shop, p["id"], JPG, "b.jpg")).json()
    imgs = r2["images"]
    assert len(imgs) == 2 and r2["image_url"] == imgs[0]["url"] == r1["images"][0]["url"]  # первое — обложка
    assert all(img_path(media_dir, i["url"]).exists() for i in imgs)

    # сделать второе обложкой
    r = await c.put(url(shop, f"/admin/products/{p['id']}/images/order"),
                    json={"image_ids": [imgs[1]["id"], imgs[0]["id"]]}, headers=A())
    assert r.status_code == 200 and r.json()["image_url"] == imgs[1]["url"]
    # покупатель видит тот же порядок
    buyer_view = (await c.get(url(shop, f"/products/{p['id']}"), headers=A(BUYER))).json()
    assert [i["id"] for i in buyer_view["images"]] == [imgs[1]["id"], imgs[0]["id"]]
    assert (await c.get(url(shop, "/products"), headers=A(BUYER))).json()[0]["image_url"] == imgs[1]["url"]

    # неполный/чужой список при сортировке → 422
    r = await c.put(url(shop, f"/admin/products/{p['id']}/images/order"), json={"image_ids": [imgs[0]["id"]]}, headers=A())
    assert r.status_code == 422

    # удалить обложку → обложкой становится следующее, файл удалён
    r = await c.delete(url(shop, f"/admin/products/{p['id']}/images/{imgs[1]['id']}"), headers=A())
    assert r.json()["image_url"] == imgs[0]["url"] and not img_path(media_dir, imgs[1]["url"]).exists()

    # удаление товара удаляет все его файлы
    await upload(c, shop, p["id"], PNG)
    await c.delete(url(shop, f"/admin/products/{p['id']}"), headers=A())
    assert not any(media_dir.rglob("*.*"))


async def test_image_limit_10(env):
    c, shop, *_ = env
    p = await add_product(c, shop)
    for _ in range(10):
        assert (await upload(c, shop, p["id"], PNG)).status_code == 201
    r = await upload(c, shop, p["id"], PNG)
    assert r.status_code == 409 and "максимум" in r.json()["detail"]


async def test_images_isolated_between_shops(env):
    c, shop, other, _ = env
    p = await add_product(c, shop)
    img = (await upload(c, shop, p["id"], PNG)).json()["images"][0]
    hb = auth(TOKEN_B, ADMIN)  # тот же человек — админ Beta
    assert (await upload(c, other, p["id"], PNG, h=hb)).status_code == 404
    assert (await c.delete(url(other, f"/admin/products/{p['id']}/images/{img['id']}"), headers=hb)).status_code == 404


@pytest.mark.parametrize("data,name", [
    (b"<svg onload=alert(1)>", "x.png"),        # не картинка, хоть и .png
    (b"<html>", "x.jpg"),
    (b"\x89PNG\r\n\x1a\n" + b"\x00" * (5 * 1024 * 1024), "big.png"),  # > 5 МБ
], ids=["svg-as-png", "html-as-jpg", "over-5mb"])
async def test_bad_images_rejected(env, data, name):
    c, shop, _, media_dir = env
    p = await add_product(c, shop)
    r = await upload(c, shop, p["id"], data, name)
    assert r.status_code == 422
    assert not any(media_dir.rglob("*.*"))


# ── корзина ──

async def test_cart_flow(env):
    c, shop, *_ = env
    tea = await add_product(c, shop, name="Чай", price="100.50")
    cake = await add_product(c, shop, name="Торт", price="300")
    h = A(BUYER)

    await c.put(url(shop, f"/cart/items/{tea['id']}"), json={"quantity": 2}, headers=h)
    r = await c.put(url(shop, f"/cart/items/{cake['id']}"), json={"quantity": 1}, headers=h)
    cart = r.json()
    assert cart["total"] == "501.00" and cart["count"] == 3
    assert [i["subtotal"] for i in cart["items"]] == ["201.00", "300.00"]

    r = await c.put(url(shop, f"/cart/items/{tea['id']}"), json={"quantity": 0}, headers=h)
    assert [i["product"]["name"] for i in r.json()["items"]] == ["Торт"]

    # корзина хранится на сервере и привязана к пользователю
    assert (await c.get(url(shop, "/cart"), headers=h)).json()["count"] == 1
    assert (await c.get(url(shop, "/cart"), headers=A(BUYER2))).json()["items"] == []

    assert (await c.delete(url(shop, "/cart"), headers=h)).json()["items"] == []


async def test_cart_rejects_out_of_stock_and_bad_quantity(env):
    c, shop, *_ = env
    p = await add_product(c, shop, in_stock=False)
    h = A(BUYER)
    assert (await c.put(url(shop, f"/cart/items/{p['id']}"), json={"quantity": 1}, headers=h)).status_code == 409
    assert (await c.put(url(shop, f"/cart/items/{p['id']}"), json={"quantity": -1}, headers=h)).status_code == 422
    assert (await c.put(url(shop, f"/cart/items/{p['id']}"), json={"quantity": 1000}, headers=h)).status_code == 422


# ── заказы ──

ORDER = {"customer_name": "Анна", "phone": "+7 (999) 123-45-67", "delivery_method": "pickup", "comment": "к 18:00"}


async def test_create_order(env):
    c, shop, *_ = env
    tea = await add_product(c, shop, name="Чай", price="100.50")
    h = A(BUYER)
    await c.put(url(shop, f"/cart/items/{tea['id']}"), json={"quantity": 3}, headers=h)

    r = await c.post(url(shop, "/orders"), json={**ORDER, "total": "0.01", "status": "done"}, headers=h)
    assert r.status_code == 201, r.text
    order = r.json()
    # итог и статус считает сервер — присланные клиентом total/status игнорируются
    assert order["total"] == "301.50" and order["status"] == "new" and order["payment_method"] == "manual"
    assert order["items"] == [{"product_id": tea["id"], "product_name": "Чай", "price": "100.50", "quantity": 3}]
    assert order["address"] is None
    # корзина очищена
    assert (await c.get(url(shop, "/cart"), headers=h)).json()["items"] == []


async def test_order_keeps_snapshot_after_product_change(env):
    c, shop, *_ = env
    tea = await add_product(c, shop, name="Чай", price="100")
    h = A(BUYER)
    await c.put(url(shop, f"/cart/items/{tea['id']}"), json={"quantity": 1}, headers=h)
    order = (await c.post(url(shop, "/orders"), json=ORDER, headers=h)).json()

    await c.patch(url(shop, f"/admin/products/{tea['id']}"), json={"name": "Чай NEW", "price": "999"}, headers=A())
    await c.delete(url(shop, f"/admin/products/{tea['id']}"), headers=A())
    [mine] = (await c.get(url(shop, "/orders"), headers=h)).json()
    assert mine["id"] == order["id"] and mine["total"] == "100.00"
    assert mine["items"][0]["product_name"] == "Чай" and mine["items"][0]["product_id"] is None


@pytest.mark.parametrize("patch,field", [
    ({"delivery_method": "delivery"}, "адрес"),
    ({"delivery_method": "delivery", "address": "   "}, "адрес"),
    ({"phone": "abc"}, "телефон"),
    ({"phone": "12"}, "телефон"),
    ({"customer_name": ""}, None),
    ({"delivery_method": "teleport"}, None),
])
async def test_order_validation(env, patch, field):
    c, shop, *_ = env
    p = await add_product(c, shop)
    h = A(BUYER)
    await c.put(url(shop, f"/cart/items/{p['id']}"), json={"quantity": 1}, headers=h)
    r = await c.post(url(shop, "/orders"), json={**ORDER, **patch}, headers=h)
    assert r.status_code == 422
    if field:
        assert field in r.text.lower()


async def test_delivery_order_with_address(env):
    c, shop, *_ = env
    p = await add_product(c, shop)
    h = A(BUYER)
    await c.put(url(shop, f"/cart/items/{p['id']}"), json={"quantity": 1}, headers=h)
    r = await c.post(url(shop, "/orders"), json={**ORDER, "delivery_method": "delivery", "address": " ул. Ленина, 1 "}, headers=h)
    assert r.status_code == 201 and r.json()["address"] == "ул. Ленина, 1"


async def test_empty_cart_and_out_of_stock_order(env):
    c, shop, *_ = env
    h = A(BUYER)
    r = await c.post(url(shop, "/orders"), json=ORDER, headers=h)
    assert r.status_code == 409 and "пуста" in r.json()["detail"]

    p = await add_product(c, shop, name="Редкий чай")
    await c.put(url(shop, f"/cart/items/{p['id']}"), json={"quantity": 1}, headers=h)
    await c.patch(url(shop, f"/admin/products/{p['id']}"), json={"in_stock": False}, headers=A())
    r = await c.post(url(shop, "/orders"), json=ORDER, headers=h)
    assert r.status_code == 409 and r.json()["unavailable"] == ["Редкий чай"]
    assert (await c.get(url(shop, "/cart"), headers=h)).json()["count"] == 1  # корзина не тронута


async def test_my_orders_scopes_and_privacy(env):
    c, shop, *_ = env
    p = await add_product(c, shop)
    h = A(BUYER)
    ids = []
    for _ in range(2):
        await c.put(url(shop, f"/cart/items/{p['id']}"), json={"quantity": 1}, headers=h)
        ids.append((await c.post(url(shop, "/orders"), json=ORDER, headers=h)).json()["id"])
    await c.patch(url(shop, f"/admin/orders/{ids[0]}"), json={"status": "done"}, headers=A())

    get = lambda scope, hh=h: c.get(url(shop, "/orders"), params={"scope": scope}, headers=hh)  # noqa: E731
    assert [o["id"] for o in (await get("active")).json()] == [ids[1]]
    assert [o["id"] for o in (await get("finished")).json()] == [ids[0]]
    assert (await get("all", A(BUYER2))).json() == []  # чужие заказы не видны
    assert "user_id" not in (await get("all")).json()[0]  # покупателю лишнее не отдаём


async def test_admin_orders_and_status_transitions(env):
    c, shop, other, _ = env
    p = await add_product(c, shop)
    h = A(BUYER)
    await c.put(url(shop, f"/cart/items/{p['id']}"), json={"quantity": 1}, headers=h)
    oid = (await c.post(url(shop, "/orders"), json=ORDER, headers=h)).json()["id"]

    [o] = (await c.get(url(shop, "/admin/orders"), headers=A())).json()
    assert o["user_id"] == BUYER and o["phone"] == ORDER["phone"]
    assert o["tg_username"] is None and o["tg_name"] == "U"  # у этого покупателя username нет
    assert (await c.get(url(shop, "/admin/orders"), params={"status": "done"}, headers=A())).json() == []

    patch = lambda s: c.patch(url(shop, f"/admin/orders/{oid}"), json={"status": s}, headers=A())  # noqa: E731
    assert (await patch("in_progress")).json()["status"] == "in_progress"
    assert (await patch("done")).json()["status"] == "done"
    r = await patch("new")  # из завершённого назад нельзя
    assert r.status_code == 409
    assert (await patch("paid")).status_code == 422  # такого статуса нет

    # админ другого магазина (тот же человек!) не трогает заказы Alpha через URL Beta
    r = await c.patch(url(other, f"/admin/orders/{oid}"), json={"status": "cancelled"}, headers=auth(TOKEN_B, ADMIN))
    assert r.status_code == 404


# ── username покупателя (этап 6.5) ──

async def test_order_stores_telegram_username_from_signed_data(env):
    c, shop, *_ = env
    p = await add_product(c, shop)
    h = auth(TOKEN_A, BUYER, first_name="Анна", username="anna_tea")
    await c.put(url(shop, f"/cart/items/{p['id']}"), json={"quantity": 1}, headers=h)
    # попытка подсунуть чужой username в теле запроса игнорируется
    r = await c.post(url(shop, "/orders"), json={**ORDER, "tg_username": "durov"}, headers=h)
    assert r.status_code == 201
    assert "tg_username" not in r.json()  # покупателю эти поля не отдаём
    [o] = (await c.get(url(shop, "/admin/orders"), headers=A())).json()
    assert o["tg_username"] == "anna_tea" and o["tg_name"] == "Анна"


# ── несколько администраторов (этап 6.5) ──

EXTRA = 400


async def test_main_admin_manages_admins(env):
    c, shop, *_ = env
    r = await c.post(url(shop, "/admin/admins"), json={"user_id": EXTRA}, headers=A())
    assert r.status_code == 201
    assert (await c.post(url(shop, "/admin/admins"), json={"user_id": EXTRA}, headers=A())).status_code == 409
    assert (await c.post(url(shop, "/admin/admins"), json={"user_id": ADMIN}, headers=A())).status_code == 409
    admins = (await c.get(url(shop, "/admin/admins"), headers=A())).json()
    assert [(a["user_id"], a["is_main"]) for a in admins] == [(ADMIN, True), (EXTRA, False)]

    me = (await c.get(url(shop, "/me"), headers=A(EXTRA))).json()
    assert me["is_admin"] is True and me["is_main_admin"] is False

    assert (await c.delete(url(shop, f"/admin/admins/{EXTRA}"), headers=A())).status_code == 204
    assert (await c.get(url(shop, "/me"), headers=A(EXTRA))).json()["is_admin"] is False
    assert (await c.delete(url(shop, f"/admin/admins/{EXTRA}"), headers=A())).status_code == 404


async def test_extra_admin_rights(env):
    c, shop, *_ = env
    await c.post(url(shop, "/admin/admins"), json={"user_id": EXTRA}, headers=A())
    h = A(EXTRA)
    # товары, категории, заказы — можно
    assert (await c.post(url(shop, "/admin/products"), json={"name": "x", "price": "1"}, headers=h)).status_code == 201
    assert (await c.post(url(shop, "/admin/categories"), json={"name": "x"}, headers=h)).status_code == 201
    assert (await c.get(url(shop, "/admin/orders"), headers=h)).status_code == 200
    # управлять админами — нельзя
    assert (await c.get(url(shop, "/admin/admins"), headers=h)).status_code == 403
    assert (await c.post(url(shop, "/admin/admins"), json={"user_id": 999}, headers=h)).status_code == 403
    assert (await c.delete(url(shop, f"/admin/admins/{EXTRA}"), headers=h)).status_code == 403
    assert (await c.post(url(shop, "/admin/invites"), headers=h)).status_code == 403


async def test_extra_admin_profile_is_remembered(env):
    c, shop, *_ = env
    await c.post(url(shop, "/admin/admins"), json={"user_id": EXTRA}, headers=A())
    await c.get(url(shop, "/me"), headers=auth(TOKEN_A, EXTRA, first_name="Ира", username="ira"))
    admins = (await c.get(url(shop, "/admin/admins"), headers=A())).json()
    assert admins[1]["name"] == "Ира" and admins[1]["username"] == "ira"


async def test_extra_admin_is_per_shop(env):
    c, shop, other, _ = env
    await c.post(url(shop, "/admin/admins"), json={"user_id": EXTRA}, headers=A())
    r = await c.post(url(other, "/admin/products"), json={"name": "x", "price": "1"}, headers=auth(TOKEN_B, EXTRA))
    assert r.status_code == 403


async def test_invite_link(env):
    c, shop, *_ = env
    r = await c.post(url(shop, "/admin/invites"), headers=A())
    assert r.status_code == 201
    link = r.json()["link"]
    assert link.startswith("https://t.me/alpha_bot?start=adm_") and len(link.split("adm_")[1]) >= 20
