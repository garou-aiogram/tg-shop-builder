import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, ApiError, type Cart, type Me, type OrderInput } from "./api";
import { alert, haptic } from "./tg";

// ── Навигация: стек экранов (без роутера — у Mini App одна «страница») ──

export type Route =
  | { name: "catalog" }
  | { name: "product"; id: number }
  | { name: "cart" }
  | { name: "checkout" }
  | { name: "orders"; placedId?: number }
  | { name: "admin" }
  | { name: "adminProduct"; id: number | null };

interface Nav {
  route: Route;
  depth: number;
  push(r: Route): void;
  back(): void;
  reset(stack: Route[]): void;
}

// ── Корзина: источник правды — сервер, здесь только последний ответ ──

interface CartApi {
  cart: Cart | null;
  quantityOf(productId: number): number;
  setQuantity(productId: number, qty: number): Promise<boolean>;
  refresh(): Promise<void>;
  pending: Set<number>;
}

interface AppCtx {
  me: Me;
  nav: Nav;
  cart: CartApi;
  draft: React.MutableRefObject<OrderInput | null>;
}

const Ctx = createContext<AppCtx | null>(null);

export function useApp(): AppCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("AppProvider missing");
  return c;
}

export function AppProvider({ me, children }: { me: Me; children: ReactNode }) {
  const [stack, setStack] = useState<Route[]>([{ name: "catalog" }]);
  const nav = useMemo<Nav>(
    () => ({
      route: stack[stack.length - 1],
      depth: stack.length,
      push: (r) => {
        setStack((s) => [...s, r]);
        window.scrollTo(0, 0);
      },
      back: () => setStack((s) => (s.length > 1 ? s.slice(0, -1) : s)),
      reset: (next) => {
        setStack(next);
        window.scrollTo(0, 0);
      },
    }),
    [stack],
  );

  const [cart, setCart] = useState<Cart | null>(null);
  const [pending, setPending] = useState<Set<number>>(new Set());

  const refresh = useCallback(async () => {
    try {
      setCart(await api.cart());
    } catch {
      /* корзина не критична для показа каталога */
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const setQuantity = useCallback(async (productId: number, qty: number) => {
    setPending((p) => new Set(p).add(productId));
    try {
      setCart(await api.setQuantity(productId, qty));
      haptic.tap();
      return true;
    } catch (e) {
      haptic.error();
      await alert(e instanceof ApiError ? e.message : "Не удалось обновить корзину");
      return false;
    } finally {
      setPending((p) => {
        const n = new Set(p);
        n.delete(productId);
        return n;
      });
    }
  }, []);

  const cartApi = useMemo<CartApi>(
    () => ({
      cart,
      pending,
      refresh,
      setQuantity,
      quantityOf: (id) => cart?.items.find((i) => i.product.id === id)?.quantity ?? 0,
    }),
    [cart, pending, refresh, setQuantity],
  );

  const draft = useRef<OrderInput | null>(null);

  return <Ctx.Provider value={{ me, nav, cart: cartApi, draft }}>{children}</Ctx.Provider>;
}
