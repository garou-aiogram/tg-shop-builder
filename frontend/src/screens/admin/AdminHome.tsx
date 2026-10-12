import { useState } from "react";
import { useApp } from "../../lib/store";
import { useBackButton } from "../../lib/tg";
import { Segmented } from "../../components/ui";
import { AdminProducts } from "./AdminProducts";
import { AdminCategories } from "./AdminCategories";
import { AdminOrders } from "./AdminOrders";
import { AdminAdmins } from "./AdminAdmins";

type Tab = "products" | "categories" | "orders" | "admins";
let savedTab: Tab = "products"; // вкладка переживает переход в редактор товара и обратно

export function AdminHome() {
  const { nav, me } = useApp();
  const [tab, setTab] = useState<Tab>(savedTab === "admins" && !me.is_main_admin ? "products" : savedTab);
  savedTab = tab;
  useBackButton(nav.back);

  return (
    <div className="page">
      <header className="topbar">
        <h1 className="topbar__title">Админка</h1>
        <span className="hint">{me.shop.name}</span>
      </header>
      <Segmented<Tab>
        value={tab}
        onChange={setTab}
        options={[
          { value: "products", label: "Товары" },
          { value: "categories", label: "Категории" },
          { value: "orders", label: "Заказы" },
          ...(me.is_main_admin ? [{ value: "admins" as Tab, label: "Админы" }] : []),
        ]}
      />
      {tab === "products" && <AdminProducts />}
      {tab === "categories" && <AdminCategories />}
      {tab === "orders" && <AdminOrders />}
      {tab === "admins" && me.is_main_admin && <AdminAdmins />}
    </div>
  );
}
