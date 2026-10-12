import { useEffect, useState } from "react";
import { api, ApiError, type Category, type Product } from "../../lib/api";
import { useApp } from "../../lib/store";
import { useMainButton } from "../../lib/tg";
import { Empty, ErrorBox, Price, ProductImage, Spinner } from "../../components/ui";

export function AdminProducts() {
  const { nav } = useApp();
  const [products, setProducts] = useState<Product[] | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    setError(null);
    Promise.all([api.products({ sort: "new" }), api.categories()])
      .then(([p, c]) => { setProducts(p); setCategories(c); })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Ошибка"));
  }, [reload]);

  useMainButton({ text: "＋ Добавить товар", onClick: () => nav.push({ name: "adminProduct", id: null }) });

  if (error) return <ErrorBox message={error} onRetry={() => setReload((n) => n + 1)} />;
  if (!products) return <Spinner />;
  if (products.length === 0) {
    return <Empty icon="📦" title="Товаров пока нет" text="Нажмите «Добавить товар» внизу экрана" />;
  }

  const catName = (id: number | null) => categories.find((c) => c.id === id)?.name ?? "Без категории";
  const needle = q.trim().toLowerCase();
  const shown = needle ? products.filter((p) => p.name.toLowerCase().includes(needle)) : products;

  return (
    <>
      {products.length > 8 && (
        <div className="search" style={{ marginBottom: 10 }}>
          <input type="search" placeholder="Найти товар" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
      )}
      <ul className="list">
        {shown.map((p) => (
          <li key={p.id}>
            <button className={p.in_stock ? "line line--btn" : "line line--btn line--off"}
              onClick={() => nav.push({ name: "adminProduct", id: p.id })}>
              <span className="line__thumb line__thumb--sm"><ProductImage product={p} /></span>
              <span className="line__body">
                <span className="line__name">{p.name}</span>
                <span className="hint">{catName(p.category_id)}{p.in_stock ? "" : " · нет в наличии"}</span>
              </span>
              <Price price={p.price} old={p.old_price} />
            </button>
          </li>
        ))}
      </ul>
    </>
  );
}
