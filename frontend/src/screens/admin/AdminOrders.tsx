import { useEffect, useState } from "react";
import { adminApi, ApiError, type AdminOrder, type OrderStatus } from "../../lib/api";
import { NEXT_STATUSES, STATUS_LABEL, dateTime, money } from "../../lib/format";
import { alert, confirm, haptic, tg, useMainButton } from "../../lib/tg";
import { Empty, ErrorBox, Spinner } from "../../components/ui";

const FILTERS: { value: OrderStatus | null; label: string }[] = [
  { value: "new", label: "Новые" },
  { value: "in_progress", label: "В работе" },
  { value: "done", label: "Выполненные" },
  { value: "cancelled", label: "Отменённые" },
  { value: null, label: "Все" },
];
let savedFilter: OrderStatus | null = "new";

export function AdminOrders() {
  const [filter, setFilter] = useState<OrderStatus | null>(savedFilter);
  savedFilter = filter;
  const [orders, setOrders] = useState<AdminOrder[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = (f: OrderStatus | null) => {
    setError(null);
    return adminApi.orders(f).then(setOrders).catch((e) => setError(e instanceof ApiError ? e.message : "Ошибка"));
  };
  useEffect(() => { setOrders(null); void load(filter); }, [filter]);
  useMainButton(null);

  const change = async (o: AdminOrder, to: OrderStatus, danger?: boolean) => {
    if (danger && !(await confirm(`Отменить заказ №${o.id}?`))) return;
    setBusyId(o.id);
    try {
      await adminApi.setOrderStatus(o.id, to);
      haptic.success();
      await load(filter); // заказ может уйти из текущего фильтра
    } catch (e) {
      haptic.error();
      await alert(e instanceof ApiError ? e.message : "Не удалось сменить статус");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <>
      <nav className="chips" style={{ marginTop: 0, marginBottom: 12 }}>
        {FILTERS.map((f) => (
          <button key={String(f.value)} className={filter === f.value ? "chip chip--on" : "chip"} onClick={() => setFilter(f.value)}>
            {f.label}
          </button>
        ))}
      </nav>

      {error ? <ErrorBox message={error} onRetry={() => void load(filter)} />
        : orders === null ? <Spinner />
        : orders.length === 0 ? <Empty icon="📭" title="Заказов нет" />
        : (
          <ul className="orders">
            {orders.map((o) => (
              <li key={o.id} className="order">
                <div className="row row--between">
                  <strong>Заказ №{o.id}</strong>
                  <span className={`status status--${o.status}`}>{STATUS_LABEL[o.status]}</span>
                </div>
                <div className="hint">{dateTime(o.created_at)}</div>

                <div className="order__customer">
                  <div>
                    <strong>{o.customer_name}</strong>
                    {o.tg_name && o.tg_name !== o.customer_name && <span className="hint"> · в Telegram: {o.tg_name}</span>}
                  </div>
                  <a className="link" href={`tel:${o.phone.replace(/[^\d+]/g, "")}`}>{o.phone}</a>
                  {o.tg_username ? (
                    <button className="btn btn--primary btn--write" onClick={() => tg?.openTelegramLink(`https://t.me/${o.tg_username}`)}>
                      ✉️ Написать @{o.tg_username}
                    </button>
                  ) : (
                    <span className="hint">У покупателя нет username в Telegram — свяжитесь по телефону</span>
                  )}
                  <div className="hint">
                    {o.delivery_method === "pickup" ? "Самовывоз" : `Доставка: ${o.address}`}
                  </div>
                  {o.comment && <div className="order__comment">💬 {o.comment}</div>}
                </div>

                <ul className="order__items">
                  {o.items.map((i, n) => (
                    <li key={n} className="row row--between">
                      <span>{i.product_name} × {i.quantity}</span>
                      <span>{money(Number(i.price) * i.quantity)}</span>
                    </li>
                  ))}
                </ul>
                <div className="row row--between"><span className="hint">Итого · оплата при получении</span><strong>{money(o.total)}</strong></div>

                {NEXT_STATUSES[o.status].length > 0 && (
                  <div className="order__actions">
                    {NEXT_STATUSES[o.status].map((n) => (
                      <button key={n.to} className={n.danger ? "btn btn--ghost-danger" : "btn btn--secondary"}
                        disabled={busyId === o.id} onClick={() => void change(o, n.to as OrderStatus, n.danger)}>
                        {n.label}
                      </button>
                    ))}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
    </>
  );
}
