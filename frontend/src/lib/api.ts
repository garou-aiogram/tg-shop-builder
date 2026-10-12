import { tg } from "./tg";

// ── Типы ответов API (деньги — строки вида "199.90") ──

export interface Shop { id: number; name: string; bot_username: string }
export interface Me { user_id: number; first_name: string; is_admin: boolean; is_main_admin: boolean; shop: Shop }
export interface Category { id: number; name: string; sort_order: number }
export interface Product {
  id: number;
  category_id: number | null;
  name: string;
  description: string;
  price: string;
  old_price: string | null;
  image_url: string | null; // обложка
  images: ProductImage[]; // все фото по порядку, первое — обложка
  in_stock: boolean;
}
export interface ProductImage { id: number; url: string }
export const MAX_PRODUCT_IMAGES = 10;
export interface CartItem { product: Product; quantity: number; subtotal: string }
export interface Cart { items: CartItem[]; total: string; count: number }
export type OrderStatus = "new" | "in_progress" | "done" | "cancelled";
export type DeliveryMethod = "pickup" | "delivery";
export interface OrderItem { product_id: number | null; product_name: string; price: string; quantity: number }
export interface Order {
  id: number;
  status: OrderStatus;
  payment_method: string;
  customer_name: string;
  phone: string;
  delivery_method: DeliveryMethod;
  address: string | null;
  comment: string;
  total: string;
  created_at: string;
  items: OrderItem[];
}
export interface OrderInput {
  customer_name: string;
  phone: string;
  delivery_method: DeliveryMethod;
  address: string | null;
  comment: string;
}
export type ProductSort = "new" | "price_asc" | "price_desc" | "discount";
export interface AdminOrder extends Order { user_id: number; tg_username: string | null; tg_name: string | null }
export interface AdminInfo { user_id: number; name: string | null; username: string | null; is_main: boolean }
export interface Invite { link: string; expires_at: string }
export interface ProductInput {
  name: string;
  description: string;
  price: string;
  old_price: string | null;
  category_id: number | null;
  in_stock: boolean;
}

// ── Клиент ──

export class ApiError extends Error {
  constructor(public status: number, message: string, public body: Record<string, unknown> = {}) {
    super(message);
  }
}

/** Один фронтенд на все магазины: магазин берётся из ?shop= в URL. */
export const shopId: number | null = (() => {
  const v = Number(new URLSearchParams(window.location.search).get("shop"));
  return Number.isInteger(v) && v > 0 ? v : null;
})();

function detailToText(detail: unknown): string {
  if (typeof detail === "string") return detail;
  // Ошибки валидации FastAPI: [{loc, msg}, ...]
  if (Array.isArray(detail)) {
    return detail
      .map((d) => String((d as { msg?: string }).msg ?? "").replace(/^Value error, /, ""))
      .filter(Boolean)
      .join("\n");
  }
  return "Ошибка запроса";
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Authorization: `tma ${tg?.initData ?? ""}` };
  const isForm = body instanceof FormData; // multipart: Content-Type с boundary ставит браузер
  if (body !== undefined && !isForm) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(`/api/shops/${shopId}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "Нет соединения. Проверьте интернет и попробуйте ещё раз.");
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, detailToText((data as { detail?: unknown }).detail), data);
  return data as T;
}

const qs = (params: Record<string, string | number | undefined | null>) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
};

export const api = {
  me: () => request<Me>("GET", "/me"),
  categories: () => request<Category[]>("GET", "/categories"),
  products: (p: { q?: string; category_id?: number | null; sort?: ProductSort }) =>
    request<Product[]>("GET", `/products${qs(p)}`),
  product: (id: number) => request<Product>("GET", `/products/${id}`),
  cart: () => request<Cart>("GET", "/cart"),
  setQuantity: (productId: number, quantity: number) =>
    request<Cart>("PUT", `/cart/items/${productId}`, { quantity }),
  clearCart: () => request<Cart>("DELETE", "/cart"),
  placeOrder: (body: OrderInput) => request<Order>("POST", "/orders", body),
  orders: (scope: "active" | "finished") => request<Order[]>("GET", `/orders${qs({ scope })}`),
};

/** Эндпоинты администратора. Права проверяет сервер: не-админ получит 403. */
export const adminApi = {
  createCategory: (name: string, sort_order: number) =>
    request<Category>("POST", "/admin/categories", { name, sort_order }),
  updateCategory: (id: number, patch: Partial<Pick<Category, "name" | "sort_order">>) =>
    request<Category>("PATCH", `/admin/categories/${id}`, patch),
  deleteCategory: (id: number) => request<void>("DELETE", `/admin/categories/${id}`),

  createProduct: (body: ProductInput) => request<Product>("POST", "/admin/products", body),
  updateProduct: (id: number, patch: Partial<ProductInput>) => request<Product>("PATCH", `/admin/products/${id}`, patch),
  deleteProduct: (id: number) => request<void>("DELETE", `/admin/products/${id}`),
  uploadImage: (id: number, file: Blob, filename: string) => {
    const form = new FormData();
    form.append("file", file, filename);
    return request<Product>("POST", `/admin/products/${id}/images`, form);
  },
  deleteImage: (productId: number, imageId: number) =>
    request<Product>("DELETE", `/admin/products/${productId}/images/${imageId}`),
  reorderImages: (productId: number, imageIds: number[]) =>
    request<Product>("PUT", `/admin/products/${productId}/images/order`, { image_ids: imageIds }),

  orders: (status: OrderStatus | null) => request<AdminOrder[]>("GET", `/admin/orders${qs({ status })}`),
  setOrderStatus: (id: number, status: OrderStatus) => request<AdminOrder>("PATCH", `/admin/orders/${id}`, { status }),

  // только главный админ
  admins: () => request<AdminInfo[]>("GET", "/admin/admins"),
  addAdmin: (user_id: number) => request<AdminInfo>("POST", "/admin/admins", { user_id }),
  removeAdmin: (user_id: number) => request<void>("DELETE", `/admin/admins/${user_id}`),
  createInvite: () => request<Invite>("POST", "/admin/invites"),
};
