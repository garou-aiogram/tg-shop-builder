import { useEffect, useState } from "react";
import { api, ApiError, shopId, type Me } from "./lib/api";
import { AppProvider, useApp } from "./lib/store";
import { insideTelegram } from "./lib/tg";
import { Empty, Spinner } from "./components/ui";
import { Catalog } from "./screens/Catalog";
import { ProductScreen } from "./screens/ProductScreen";
import { CartScreen } from "./screens/CartScreen";
import { Checkout } from "./screens/Checkout";
import { Orders } from "./screens/Orders";
import { AdminHome } from "./screens/admin/AdminHome";
import { ProductEditor } from "./screens/admin/ProductEditor";

function Screens() {
  const { nav, me } = useApp();
  const r = nav.route;
  switch (r.name) {
    case "catalog": return <Catalog />;
    case "product": return <ProductScreen key={r.id} id={r.id} />;
    case "cart": return <CartScreen />;
    case "checkout": return <Checkout />;
    case "orders": return <Orders placedId={r.placedId} />;
    // Раздел видят только те, кого сервер признал админом; API всё равно проверяет права сам
    case "admin": return me.is_admin ? <AdminHome /> : <Catalog />;
    case "adminProduct": return me.is_admin ? <ProductEditor key={String(r.id)} id={r.id} /> : <Catalog />;
  }
}

export function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!shopId || !insideTelegram) return;
    api.me().then(setMe).catch((e) => setError(e instanceof ApiError ? e.message : "Ошибка"));
  }, []);

  if (!shopId) return <div className="page"><Empty icon="🤔" title="Магазин не указан" /></div>;
  if (!insideTelegram) {
    return <div className="page"><Empty icon="📱" title="Откройте магазин в Telegram" text="Витрина работает внутри Telegram — через кнопку «Магазин» в боте." /></div>;
  }
  if (error) return <div className="page"><Empty icon="⚠️" title="Магазин недоступен" text={error} /></div>;
  if (!me) return <div className="page"><Spinner /></div>;

  return (
    <AppProvider me={me}>
      <Screens />
    </AppProvider>
  );
}
