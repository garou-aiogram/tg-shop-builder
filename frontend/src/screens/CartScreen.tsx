import { money, plural } from "../lib/format";
import { useApp } from "../lib/store";
import { confirm, useBackButton, useMainButton } from "../lib/tg";
import { api } from "../lib/api";
import { Empty, Price, ProductImage, Spinner, Stepper } from "../components/ui";

export function CartScreen() {
  const { nav, cart } = useApp();
  const data = cart.cart;
  const unavailable = data?.items.filter((i) => !i.product.in_stock) ?? [];

  useBackButton(nav.back);
  useMainButton(
    data && data.items.length > 0
      ? {
          text: unavailable.length ? "Уберите товары, которых нет" : `Оформить заказ · ${money(data.total)}`,
          disabled: unavailable.length > 0,
          onClick: () => nav.push({ name: "checkout" }),
        }
      : null,
  );

  if (!data) return <div className="page"><Spinner /></div>;
  if (data.items.length === 0) {
    return (
      <div className="page">
        <Empty
          icon="🧺"
          title="Корзина пуста"
          text="Добавьте товары из каталога"
          action={<button className="btn btn--secondary" onClick={() => nav.reset([{ name: "catalog" }])}>В каталог</button>}
        />
      </div>
    );
  }

  const clear = async () => {
    if (await confirm("Очистить корзину?")) {
      await api.clearCart();
      await cart.refresh();
    }
  };

  return (
    <div className="page">
      <header className="topbar">
        <h1 className="topbar__title">Корзина</h1>
        <button className="link" onClick={clear}>Очистить</button>
      </header>

      <ul className="list">
        {data.items.map(({ product: p, quantity, subtotal }) => (
          <li key={p.id} className={p.in_stock ? "line" : "line line--off"}>
            <button className="line__thumb" onClick={() => nav.push({ name: "product", id: p.id })} aria-label={p.name}>
              <ProductImage product={p} />
            </button>
            <div className="line__body">
              <div className="line__name">{p.name}</div>
              {p.in_stock ? <Price price={p.price} old={p.old_price} /> : <span className="danger">Нет в наличии</span>}
              <div className="line__controls">
                {p.in_stock ? (
                  <Stepper compact value={quantity} busy={cart.pending.has(p.id)} onChange={(v) => cart.setQuantity(p.id, v)} />
                ) : (
                  <button className="link link--danger" onClick={() => cart.setQuantity(p.id, 0)}>Убрать</button>
                )}
                <span className="line__sum">{money(subtotal)}</span>
              </div>
            </div>
          </li>
        ))}
      </ul>

      <div className="total">
        <span>Итого · {data.count} {plural(data.count, "товар", "товара", "товаров")}</span>
        <strong>{money(data.total)}</strong>
      </div>
    </div>
  );
}
