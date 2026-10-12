import { useState } from "react";
import { api, ApiError, type DeliveryMethod, type OrderInput } from "../lib/api";
import { money } from "../lib/format";
import { useApp } from "../lib/store";
import { alert, haptic, tg, useBackButton, useMainButton } from "../lib/tg";
import { Segmented } from "../components/ui";

function defaultName(): string {
  const u = tg?.initDataUnsafe.user;
  return [u?.first_name, u?.last_name].filter(Boolean).join(" ");
}

type Errors = Partial<Record<keyof OrderInput, string>>;

function validate(f: OrderInput): Errors {
  const e: Errors = {};
  if (!f.customer_name.trim()) e.customer_name = "Укажите имя";
  const digits = f.phone.replace(/\D/g, "").length;
  if (!/^\+?[\d\s()-]+$/.test(f.phone.trim()) || digits < 5 || digits > 15) e.phone = "Проверьте номер телефона";
  if (f.delivery_method === "delivery" && !f.address?.trim()) e.address = "Укажите адрес доставки";
  return e;
}

export function Checkout() {
  const { nav, cart, draft } = useApp();
  const [form, setForm] = useState<OrderInput>(
    draft.current ?? { customer_name: defaultName(), phone: "", delivery_method: "pickup", address: "", comment: "" },
  );
  const [errors, setErrors] = useState<Errors>({});
  const [sending, setSending] = useState(false);
  const set = <K extends keyof OrderInput>(k: K, v: OrderInput[K]) => {
    const next = { ...form, [k]: v };
    setForm(next);
    draft.current = next; // черновик переживает возврат в корзину
    if (errors[k]) setErrors({ ...errors, [k]: undefined });
  };

  const submit = async () => {
    const e = validate(form);
    setErrors(e);
    if (Object.keys(e).length) {
      haptic.error();
      return;
    }
    setSending(true);
    try {
      const order = await api.placeOrder({
        ...form,
        address: form.delivery_method === "delivery" ? form.address : null,
      });
      haptic.success();
      draft.current = null;
      await cart.refresh();
      nav.reset([{ name: "catalog" }, { name: "orders", placedId: order.id }]);
    } catch (err) {
      haptic.error();
      if (err instanceof ApiError && err.status === 409) {
        const list = (err.body.unavailable as string[] | undefined)?.join(", ");
        await alert(list ? `${err.message}: ${list}` : err.message);
        await cart.refresh();
        nav.back();
      } else {
        await alert(err instanceof ApiError ? err.message : "Не удалось оформить заказ");
      }
    } finally {
      setSending(false);
    }
  };

  useBackButton(sending ? null : nav.back);
  const total = cart.cart?.total ?? "0";
  useMainButton({ text: `Подтвердить заказ · ${money(total)}`, onClick: submit, progress: sending });

  return (
    <div className="page">
      <header className="topbar"><h1 className="topbar__title">Оформление</h1></header>

      <form className="form" onSubmit={(e) => { e.preventDefault(); void submit(); }} noValidate>
        <label className="field">
          <span className="field__label">Имя</span>
          <input value={form.customer_name} onChange={(e) => set("customer_name", e.target.value)} autoComplete="name" maxLength={128} />
          {errors.customer_name && <span className="field__error">{errors.customer_name}</span>}
        </label>

        <label className="field">
          <span className="field__label">Телефон</span>
          <input type="tel" inputMode="tel" placeholder="+7 999 123-45-67" value={form.phone}
            onChange={(e) => set("phone", e.target.value)} autoComplete="tel" maxLength={25} />
          {errors.phone && <span className="field__error">{errors.phone}</span>}
        </label>

        <div className="field">
          <span className="field__label">Способ получения</span>
          <Segmented<DeliveryMethod>
            value={form.delivery_method}
            onChange={(v) => { haptic.select(); set("delivery_method", v); }}
            options={[{ value: "pickup", label: "Самовывоз" }, { value: "delivery", label: "Доставка" }]}
          />
        </div>

        {form.delivery_method === "delivery" && (
          <label className="field">
            <span className="field__label">Адрес доставки</span>
            <textarea rows={2} placeholder="Улица, дом, квартира" value={form.address ?? ""}
              onChange={(e) => set("address", e.target.value)} autoComplete="street-address" maxLength={500} />
            {errors.address && <span className="field__error">{errors.address}</span>}
          </label>
        )}

        <label className="field">
          <span className="field__label">Комментарий <span className="hint">— необязательно</span></span>
          <textarea rows={2} placeholder="Удобное время, пожелания" value={form.comment}
            onChange={(e) => set("comment", e.target.value)} maxLength={1000} />
        </label>

        <p className="hint">Оплата при получении. Администратор магазина свяжется с вами для подтверждения заказа.</p>
        <button type="submit" hidden />
      </form>
    </div>
  );
}
