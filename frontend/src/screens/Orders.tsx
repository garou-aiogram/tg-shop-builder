import { useEffect, useState } from "react";
import { api, ApiError, type Order } from "../lib/api";
import { STATUS_LABEL, dateTime, money } from "../lib/format";
import { useApp } from "../lib/store";
import { useBackButton, useMainButton } from "../lib/tg";
import { Empty, ErrorBox, Segmented, Spinner } from "../components/ui";

type Scope = "active" | "finished";

export function Orders({ placedId }: { placedId?: number }) {
  const { nav } = useApp();
  const [scope, setScope] = useState<Scope>("active");
  const [orders, setOrders] = useState<Order[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let alive = true;
    setOrders(null);
    setError(null);
    api.orders(scope)
      .then((o) => alive && setOrders(o))
      .catch((e) => alive && setError(e instanceof ApiError ? e.message : "Ошибка"));
    return () => { alive = false; };
  }, [scope, reload]);

  useBackButton(nav.back);
  useMainButton(placedId ? { text: "Вернуться в каталог", onClick: () => nav.reset([{ name: "catalog" }]) } : null);

  return (
    <div className="page">
      <header className="topbar"><h1 className="topbar__title">Мои заказы</h1></header>

      {placedId && (
        <div className="success">
          <div className="success__icon">✅</div>
          <div>
            <div className="success__title">Заказ №{placedId} оформлен</div>
            <div className="hint">Администратор свяжется с вами в Telegram или по телефону.</div>
          </div>
        </div>
      )}

      <Segmented<Scope>
        value={scope}
        onChange={setScope}
        options={[{ value: "active", label: "Активные" }, { value: "finished", label: "Завершённые" }]}
      />

      {error ? (
        <ErrorBox message={error} onRetry={() => setReload((n) => n + 1)} />
      ) : orders === null ? (
        <Spinner />
      ) : orders.length === 0 ? (
        <Empty icon="📦" title={scope === "active" ? "Активных заказов нет" : "Завершённых заказов нет"} />
      ) : (
        <ul className="orders">
          {orders.map((o) => <OrderCard key={o.id} order={o} highlight={o.id === placedId} />)}
        </ul>
      )}
    </div>
  );
}

function OrderCard({ order: o, highlight }: { order: Order; highlight: boolean }) {
  return (
    <li className={highlight ? "order order--hl" : "order"}>
      <div className="row row--between">
        <strong>Заказ №{o.id}</strong>
        <span className={`status status--${o.status}`}>{STATUS_LABEL[o.status]}</span>
      </div>
      <div className="hint">{dateTime(o.created_at)}</div>
      <ul className="order__items">
        {o.items.map((i, n) => (
          <li key={n} className="row row--between">
            <span>{i.product_name} × {i.quantity}</span>
            <span>{money(Number(i.price) * i.quantity)}</span>
          </li>
        ))}
      </ul>
      <div className="row row--between order__total">
        <span className="hint">
          {o.delivery_method === "pickup" ? "Самовывоз" : `Доставка: ${o.address}`}
        </span>
        <strong>{money(o.total)}</strong>
      </div>
    </li>
  );
}
