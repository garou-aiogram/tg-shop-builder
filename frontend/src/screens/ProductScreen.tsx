import { useEffect, useState } from "react";
import { api, ApiError, type Product } from "../lib/api";
import { money } from "../lib/format";
import { useApp } from "../lib/store";
import { haptic, useBackButton, useMainButton } from "../lib/tg";
import { ErrorBox, Gallery, Price, Spinner, Stepper } from "../components/ui";

export function ProductScreen({ id }: { id: number }) {
  const { nav, cart } = useApp();
  const [product, setProduct] = useState<Product | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inCart = cart.quantityOf(id);
  const [qty, setQty] = useState(Math.max(inCart, 1));

  useEffect(() => {
    api.product(id).then(setProduct).catch((e) => setError(e instanceof ApiError ? e.message : "Ошибка"));
  }, [id]);

  useBackButton(nav.back);

  const busy = cart.pending.has(id);
  const synced = inCart > 0 && inCart === qty;
  useMainButton(
    product && product.in_stock
      ? synced
        ? { text: "Перейти в корзину", onClick: () => nav.push({ name: "cart" }) }
        : {
            text: `${inCart > 0 ? "Обновить корзину" : "В корзину"} · ${money(Number(product.price) * qty)}`,
            progress: busy,
            onClick: async () => {
              if (await cart.setQuantity(id, qty)) haptic.success();
            },
          }
      : null,
  );

  if (error) return <div className="page"><ErrorBox message={error} /></div>;
  if (!product) return <div className="page"><Spinner /></div>;

  return (
    <div className="page page--flush">
      <Gallery product={product} />
      <div className="section">
        <h1 className="title">{product.name}</h1>
        <Price price={product.price} old={product.old_price} large />
        {product.in_stock ? (
          <div className="row row--between">
            <span className="hint">{inCart > 0 ? `В корзине: ${inCart}` : "Количество"}</span>
            <Stepper value={qty} min={1} onChange={setQty} busy={busy} />
          </div>
        ) : (
          <div className="notice">Сейчас нет в наличии</div>
        )}
      </div>
      {product.description && (
        <div className="section">
          <h2 className="subtitle">Описание</h2>
          <p className="text">{product.description}</p>
        </div>
      )}
    </div>
  );
}
