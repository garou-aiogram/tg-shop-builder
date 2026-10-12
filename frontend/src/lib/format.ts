const rub = new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB", maximumFractionDigits: 2, minimumFractionDigits: 0 });

/** "1500.00" → "1 500 ₽", "99.90" → "99,9 ₽" — Number только для показа, не для расчётов. */
export const money = (v: string | number) => rub.format(Number(v));

export function discountPercent(price: string, old: string | null): number | null {
  if (!old) return null;
  const p = Number(price), o = Number(old);
  return o > p ? Math.round((1 - p / o) * 100) : null;
}

export const STATUS_LABEL: Record<string, string> = {
  new: "Новый",
  in_progress: "В работе",
  done: "Выполнен",
  cancelled: "Отменён",
};

export function plural(n: number, one: string, few: string, many: string): string {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
}

const dateFmt = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" });
export const dateTime = (iso: string) => dateFmt.format(new Date(iso));

/** Цвет-заглушка для товара без фото: стабильный по названию. */
export function placeholderHue(name: string): number {
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return h;
}

/** «199,9» / «199.90» / « 1 500 » → "199.90" | null (пусто). Бросает Error с понятным текстом. */
export function parseMoney(raw: string, field: string): string | null {
  const v = raw.replace(/\s/g, "").replace(",", ".");
  if (!v) return null;
  if (!/^\d{1,10}(\.\d{1,2})?$/.test(v)) throw new Error(`${field}: число, максимум 2 знака после запятой`);
  return Number(v).toFixed(2);
}

/** Какие статусы можно выставить из текущего — зеркало TRANSITIONS на сервере. */
export const NEXT_STATUSES: Record<string, { to: string; label: string; danger?: boolean }[]> = {
  new: [{ to: "in_progress", label: "Взять в работу" }, { to: "done", label: "Выполнен" }, { to: "cancelled", label: "Отменить", danger: true }],
  in_progress: [{ to: "done", label: "Выполнен" }, { to: "new", label: "Вернуть в новые" }, { to: "cancelled", label: "Отменить", danger: true }],
  done: [],
  cancelled: [],
};
