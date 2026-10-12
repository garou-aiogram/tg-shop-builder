import { useState, type ReactNode } from "react";
import type { Product } from "../lib/api";
import { discountPercent, money, placeholderHue } from "../lib/format";

export function Price({ price, old, large }: { price: string; old: string | null; large?: boolean }) {
  const pct = discountPercent(price, old);
  return (
    <span className={large ? "price price--lg" : "price"}>
      <span className={pct ? "price__now price__now--sale" : "price__now"}>{money(price)}</span>
      {pct && <s className="price__old">{money(old!)}</s>}
    </span>
  );
}

export function ProductImage({ product, className }: { product: Pick<Product, "name" | "image_url">; className?: string }) {
  if (product.image_url) {
    return <img className={`pimg ${className ?? ""}`} src={product.image_url} alt={product.name} loading="lazy" />;
  }
  const hue = placeholderHue(product.name);
  return (
    <div
      className={`pimg pimg--empty ${className ?? ""}`}
      style={{ background: `linear-gradient(135deg, hsl(${hue} 60% 62%), hsl(${(hue + 40) % 360} 65% 50%))` }}
      aria-hidden
    >
      {product.name.trim().charAt(0).toUpperCase()}
    </div>
  );
}

export function Stepper({
  value, onChange, min = 0, max = 999, busy, compact,
}: { value: number; onChange: (v: number) => void; min?: number; max?: number; busy?: boolean; compact?: boolean }) {
  return (
    <div className={compact ? "stepper stepper--compact" : "stepper"} aria-busy={busy}>
      <button type="button" aria-label="Меньше" disabled={busy || value <= min} onClick={() => onChange(value - 1)}>−</button>
      <span className="stepper__value">{value}</span>
      <button type="button" aria-label="Больше" disabled={busy || value >= max} onClick={() => onChange(value + 1)}>+</button>
    </div>
  );
}

export function Spinner() {
  return <div className="spinner" role="status" aria-label="Загрузка" />;
}

export function Empty({ icon, title, text, action }: { icon: string; title: string; text?: string; action?: ReactNode }) {
  return (
    <div className="empty">
      <div className="empty__icon">{icon}</div>
      <div className="empty__title">{title}</div>
      {text && <div className="empty__text">{text}</div>}
      {action}
    </div>
  );
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <Empty
      icon="⚠️"
      title="Не получилось загрузить"
      text={message}
      action={onRetry && <button className="btn btn--secondary" onClick={onRetry}>Повторить</button>}
    />
  );
}

export function Segmented<T extends string>({
  value, options, onChange,
}: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="segmented" role="tablist">
      {options.map((o) => (
        <button
          key={o.value}
          role="tab"
          aria-selected={o.value === value}
          className={o.value === value ? "segmented__item segmented__item--on" : "segmented__item"}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** Фото товара: свайп по горизонтали (CSS scroll-snap, без библиотек) + точки-индикаторы. */
export function Gallery({ product }: { product: Pick<Product, "name" | "image_url" | "images"> }) {
  const [index, setIndex] = useState(0);
  if (product.images.length <= 1) return <ProductImage product={product} className="hero" />;
  return (
    <div className="gallery">
      <div
        className="gallery__track"
        onScroll={(e) => {
          const el = e.currentTarget;
          setIndex(Math.round(el.scrollLeft / el.clientWidth));
        }}
      >
        {product.images.map((img, i) => (
          <img key={img.id} className="gallery__img" src={img.url} alt={`${product.name}, фото ${i + 1}`} loading={i ? "lazy" : "eager"} />
        ))}
      </div>
      <div className="gallery__dots" aria-hidden>
        {product.images.map((img, i) => <span key={img.id} className={i === index ? "dot dot--on" : "dot"} />)}
      </div>
    </div>
  );
}
