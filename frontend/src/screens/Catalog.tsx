import { useEffect, useState } from "react";
import { api, ApiError, type Category, type Product, type ProductSort } from "../lib/api";
import { money, plural } from "../lib/format";
import { useApp } from "../lib/store";
import { haptic, useBackButton, useMainButton } from "../lib/tg";
import { Empty, ErrorBox, Price, ProductImage, Spinner, Stepper } from "../components/ui";

const SORTS: { value: ProductSort; label: string }[] = [
  { value: "new", label: "Сначала новые" },
  { value: "price_asc", label: "Сначала дешевле" },
  { value: "price_desc", label: "Сначала дороже" },
  { value: "discount", label: "По скидке" },
];

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

// Фильтры переживают переход в карточку товара и обратно
const saved = { q: "", category: null as number | null, sort: "new" as ProductSort };

export function Catalog() {
  const { me, nav, cart } = useApp();
  const [q, setQ] = useState(saved.q);
  const [category, setCategory] = useState<number | null>(saved.category);
  const [sort, setSort] = useState<ProductSort>(saved.sort);
  const query = useDebounced(q, 300);
  Object.assign(saved, { q, category, sort });

  const [categories, setCategories] = useState<Category[]>([]);
  const [products, setProducts] = useState<Product[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    api.categories().then(setCategories).catch(() => setCategories([]));
  }, []);

  useEffect(() => {
    let alive = true;
    setError(null);
    api
      .products({ q: query, category_id: category, sort })
      .then((p) => alive && setProducts(p))
      .catch((e) => alive && setError(e instanceof ApiError ? e.message : "Ошибка"));
    return () => {
      alive = false;
    };
  }, [query, category, sort, reload]);

  useBackButton(null);
  const count = cart.cart?.count ?? 0;
  useMainButton(
    count > 0
      ? { text: `Корзина · ${count} ${plural(count, "товар", "товара", "товаров")} · ${money(cart.cart!.total)}`, onClick: () => nav.push({ name: "cart" }) }
      : null,
  );

  const filtered = Boolean(query || category !== null);

  return (
    <div className="page">
      <header className="topbar">
        <h1 className="topbar__title">{me.shop.name}</h1>
        <div className="topbar__actions">
          {me.is_admin && (
            <button className="chip chip--accent" onClick={() => nav.push({ name: "admin" })}>⚙️ Админка</button>
          )}
          <button className="chip" onClick={() => nav.push({ name: "orders" })}>📦 Заказы</button>
        </div>
      </header>

      <div className="search">
        <input
          type="search"
          inputMode="search"
          placeholder="Поиск товаров"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          aria-label="Поиск товаров"
        />
      </div>

      {categories.length > 0 && (
        <nav className="chips" aria-label="Категории">
          <button className={category === null ? "chip chip--on" : "chip"} onClick={() => { haptic.select(); setCategory(null); }}>
            Все
          </button>
          {categories.map((c) => (
            <button
              key={c.id}
              className={category === c.id ? "chip chip--on" : "chip"}
              onClick={() => { haptic.select(); setCategory(c.id); }}
            >
              {c.name}
            </button>
          ))}
        </nav>
      )}

      <div className="toolbar">
        <span className="hint">{products ? `${products.length} ${plural(products.length, "товар", "товара", "товаров")}` : ""}</span>
        <select className="select" value={sort} onChange={(e) => setSort(e.target.value as ProductSort)} aria-label="Сортировка">
          {SORTS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
      </div>

      {error ? (
        <ErrorBox message={error} onRetry={() => setReload((n) => n + 1)} />
      ) : products === null ? (
        <Spinner />
      ) : products.length === 0 ? (
        filtered ? (
          <Empty icon="🔍" title="Ничего не нашлось" text="Попробуйте изменить запрос или категорию" />
        ) : (
          <Empty icon="🛍" title="Скоро здесь появятся товары" text={me.is_admin ? "Добавьте первый товар в админке" : "Загляните чуть позже"} />
        )
      ) : (
        <div className="grid">
          {products.map((p) => <ProductCard key={p.id} product={p} />)}
        </div>
      )}
    </div>
  );
}

function ProductCard({ product: p }: { product: Product }) {
  const { nav, cart } = useApp();
  const qty = cart.quantityOf(p.id);
  const busy = cart.pending.has(p.id);
  return (
    <article className={p.in_stock ? "card" : "card card--off"}>
      <button className="card__open" onClick={() => nav.push({ name: "product", id: p.id })} aria-label={p.name}>
        <div className="card__media">
          <ProductImage product={p} />
          {!p.in_stock && <span className="badge badge--muted">Нет в наличии</span>}
          {p.in_stock && p.old_price && Number(p.old_price) > Number(p.price) && (
            <span className="badge badge--sale">−{Math.round((1 - Number(p.price) / Number(p.old_price)) * 100)}%</span>
          )}
        </div>
        <div className="card__name">{p.name}</div>
      </button>
      <div className="card__bottom">
        <Price price={p.price} old={p.old_price} />
        {p.in_stock &&
          (qty > 0 ? (
            <Stepper compact value={qty} busy={busy} onChange={(v) => cart.setQuantity(p.id, v)} />
          ) : (
            <button className="btn btn--primary btn--small" disabled={busy} onClick={() => cart.setQuantity(p.id, 1)}>
              В корзину
            </button>
          ))}
      </div>
    </article>
  );
}
