import { useEffect, useRef, useState } from "react";
import { adminApi, api, ApiError, MAX_PRODUCT_IMAGES, type Category, type Product, type ProductInput } from "../../lib/api";
import { parseMoney } from "../../lib/format";
import { IMAGE_ACCEPT, prepareImage } from "../../lib/image";
import { useApp } from "../../lib/store";
import { alert, confirm, haptic, useBackButton, useMainButton } from "../../lib/tg";
import { ErrorBox, Spinner } from "../../components/ui";

interface Form {
  name: string;
  description: string;
  price: string;
  old_price: string;
  category_id: number | null;
  in_stock: boolean;
}

const EMPTY: Form = { name: "", description: "", price: "", old_price: "", category_id: null, in_stock: true };

const toForm = (p: Product): Form => ({
  name: p.name,
  description: p.description,
  price: p.price,
  old_price: p.old_price ?? "",
  category_id: p.category_id,
  in_stock: p.in_stock,
});

type Errors = Partial<Record<keyof Form, string>>;
type Pending = { blob: Blob; name: string; url: string; key: string };

function validate(f: Form): { errors: Errors; body?: ProductInput } {
  const errors: Errors = {};
  if (!f.name.trim()) errors.name = "Укажите название";
  let price: string | null = null, old: string | null = null;
  try { price = parseMoney(f.price, "Цена"); if (price === null) errors.price = "Укажите цену"; }
  catch (e) { errors.price = (e as Error).message; }
  try { old = parseMoney(f.old_price, "Старая цена"); }
  catch (e) { errors.old_price = (e as Error).message; }
  if (price !== null && old !== null && Number(old) <= Number(price)) {
    errors.old_price = "Старая цена должна быть больше текущей";
  }
  if (Object.keys(errors).length) return { errors };
  return {
    errors,
    body: {
      name: f.name.trim(), description: f.description.trim(), price: price!, old_price: old,
      category_id: f.category_id, in_stock: f.in_stock,
    },
  };
}

export function ProductEditor({ id }: { id: number | null }) {
  const { nav } = useApp();
  const [product, setProduct] = useState<Product | null>(null);
  const [form, setForm] = useState<Form | null>(id === null ? EMPTY : null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [errors, setErrors] = useState<Errors>({});
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  // Новый товар: фото выбраны, но загрузятся после создания (нужен id товара)
  const [pending, setPending] = useState<Pending[]>([]);
  const [photoBusy, setPhotoBusy] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.categories().then(setCategories).catch(() => {});
    if (id !== null) {
      api.product(id)
        .then((p) => { setProduct(p); setForm(toForm(p)); })
        .catch((e) => setLoadError(e instanceof ApiError ? e.message : "Ошибка"));
    }
  }, [id]);

  const pendingRef = useRef(pending);
  pendingRef.current = pending;
  useEffect(() => () => pendingRef.current.forEach((x) => URL.revokeObjectURL(x.url)), []);

  const set = <K extends keyof Form>(k: K, v: Form[K]) => {
    setForm((f) => ({ ...f!, [k]: v }));
    if (errors[k]) setErrors((e) => ({ ...e, [k]: undefined }));
  };

  const save = async () => {
    if (!form) return;
    const { errors: errs, body } = validate(form);
    setErrors(errs);
    if (!body) { haptic.error(); return; }
    setSaving(true);
    try {
      if (id === null) {
        const created = await adminApi.createProduct(body);
        let failed = 0;
        for (const ph of pending) {  // по одному, в выбранном порядке: первое станет обложкой
          try { await adminApi.uploadImage(created.id, ph.blob, ph.name); } catch { failed++; }
        }
        if (failed) await alert(`Товар создан, но ${failed} фото не загрузилось — добавьте их ещё раз в редакторе.`);
      } else {
        await adminApi.updateProduct(id, body);
      }
      haptic.success();
      nav.back();
    } catch (e) {
      haptic.error();
      await alert(e instanceof ApiError ? e.message : "Не удалось сохранить");
    } finally {
      setSaving(false);
    }
  };

  const photoCount = id === null ? pending.length : product?.images.length ?? 0;
  const slots = MAX_PRODUCT_IMAGES - photoCount;

  const pickPhotos = async (files: FileList | null) => {
    if (!files?.length) return;
    const list = Array.from(files);
    if (list.length > slots) await alert(`Можно добавить ещё ${slots} фото из ${MAX_PRODUCT_IMAGES}. Лишние пропущены.`);
    setPhotoBusy(true);
    try {
      for (const file of list.slice(0, slots)) {
        let prepared;
        try { prepared = await prepareImage(file); }
        catch (e) { await alert(`${file.name}: ${e instanceof Error ? e.message : "не удалось прочитать"}`); continue; }
        if (id === null) {
          const url = URL.createObjectURL(prepared.blob);
          setPending((xs) => [...xs, { ...prepared, url, key: url }]);
        } else {
          try { setProduct(await adminApi.uploadImage(id, prepared.blob, prepared.name)); }
          catch (e) { await alert(e instanceof ApiError ? e.message : "Не удалось загрузить фото"); break; }
        }
      }
      haptic.success();
    } finally {
      setPhotoBusy(false);
      if (fileInput.current) fileInput.current.value = ""; // чтобы можно было выбрать те же файлы снова
    }
  };

  /** Новый порядок фото: from → to (to = 0 — сделать обложкой). */
  const movePhoto = async (from: number, to: number) => {
    if (id === null) {
      setPending((xs) => { const n = [...xs]; const [x] = n.splice(from, 1); n.splice(to, 0, x); return n; });
      return;
    }
    if (!product) return;
    const ids = product.images.map((i) => i.id);
    const [x] = ids.splice(from, 1);
    ids.splice(to, 0, x);
    setPhotoBusy(true);
    try { setProduct(await adminApi.reorderImages(id, ids)); haptic.tap(); }
    catch (e) { await alert(e instanceof ApiError ? e.message : "Ошибка"); }
    finally { setPhotoBusy(false); }
  };

  const removePhoto = async (index: number) => {
    if (id === null) {
      setPending((xs) => { URL.revokeObjectURL(xs[index].url); return xs.filter((_, i) => i !== index); });
      return;
    }
    if (!product || !(await confirm("Удалить это фото?"))) return;
    setPhotoBusy(true);
    try { setProduct(await adminApi.deleteImage(id, product.images[index].id)); }
    catch (e) { await alert(e instanceof ApiError ? e.message : "Ошибка"); }
    finally { setPhotoBusy(false); }
  };

  const remove = async () => {
    if (id === null || !(await confirm("Удалить товар? Оформленные заказы с ним сохранятся."))) return;
    setSaving(true);
    try { await adminApi.deleteProduct(id); haptic.success(); nav.back(); }
    catch (e) { await alert(e instanceof ApiError ? e.message : "Не удалось удалить"); setSaving(false); }
  };

  useBackButton(saving ? null : nav.back);
  useMainButton(form ? { text: id === null ? "Создать товар" : "Сохранить", onClick: save, progress: saving } : null);

  if (loadError) return <div className="page"><ErrorBox message={loadError} /></div>;
  if (!form) return <div className="page"><Spinner /></div>;

  const photos: { key: string | number; url: string }[] =
    id === null ? pending.map((x) => ({ key: x.key, url: x.url })) : (product?.images ?? []).map((i) => ({ key: i.id, url: i.url }));

  return (
    <div className="page">
      <header className="topbar"><h1 className="topbar__title">{id === null ? "Новый товар" : "Товар"}</h1></header>

      <section className="photos" aria-busy={photoBusy}>
        <div className="photos__head">
          <span className="field__label">Фото · {photos.length} из {MAX_PRODUCT_IMAGES}</span>
          {photoBusy && <span className="hint">Загрузка…</span>}
        </div>
        <div className="photos__strip">
          {photos.map((ph, i) => (
            <div key={ph.key} className="thumb">
              <img src={ph.url} alt={`Фото ${i + 1}`} />
              {i === 0 && <span className="thumb__cover">Обложка</span>}
              <div className="thumb__bar">
                <button type="button" aria-label="Левее" disabled={photoBusy || i === 0} onClick={() => void movePhoto(i, i - 1)}>‹</button>
                {i > 0 && <button type="button" aria-label="Сделать обложкой" disabled={photoBusy} onClick={() => void movePhoto(i, 0)}>★</button>}
                <button type="button" aria-label="Удалить фото" disabled={photoBusy} onClick={() => void removePhoto(i)}>✕</button>
                <button type="button" aria-label="Правее" disabled={photoBusy || i === photos.length - 1} onClick={() => void movePhoto(i, i + 1)}>›</button>
              </div>
            </div>
          ))}
          {slots > 0 && (
            <button type="button" className="thumb thumb--add" disabled={photoBusy} onClick={() => fileInput.current?.click()}>
              <span>＋</span>
              <span className="hint">{photos.length ? "Ещё фото" : "Добавить фото"}</span>
            </button>
          )}
        </div>
        <span className="hint">Первое фото — обложка в каталоге. JPEG, PNG или WebP; большие уменьшатся автоматически.</span>
        <input ref={fileInput} type="file" accept={IMAGE_ACCEPT} multiple hidden onChange={(e) => void pickPhotos(e.target.files)} />
      </section>

      <form className="form" onSubmit={(e) => { e.preventDefault(); void save(); }} noValidate>
        <label className="field">
          <span className="field__label">Название</span>
          <input value={form.name} maxLength={128} onChange={(e) => set("name", e.target.value)} />
          {errors.name && <span className="field__error">{errors.name}</span>}
        </label>

        <div className="field-row">
          <label className="field">
            <span className="field__label">Цена, ₽</span>
            <input inputMode="decimal" placeholder="0" value={form.price} onChange={(e) => set("price", e.target.value)} />
            {errors.price && <span className="field__error">{errors.price}</span>}
          </label>
          <label className="field">
            <span className="field__label">Старая цена, ₽</span>
            <input inputMode="decimal" placeholder="для скидки" value={form.old_price} onChange={(e) => set("old_price", e.target.value)} />
            {errors.old_price && <span className="field__error">{errors.old_price}</span>}
          </label>
        </div>

        <label className="field">
          <span className="field__label">Категория</span>
          <select className="field__select" value={form.category_id ?? ""}
            onChange={(e) => set("category_id", e.target.value ? Number(e.target.value) : null)}>
            <option value="">Без категории</option>
            {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>

        <label className="field">
          <span className="field__label">Описание</span>
          <textarea rows={4} maxLength={4000} value={form.description} onChange={(e) => set("description", e.target.value)} />
        </label>

        <label className="toggle">
          <span>В наличии</span>
          <input type="checkbox" checked={form.in_stock} onChange={(e) => set("in_stock", e.target.checked)} />
        </label>
        <button type="submit" hidden />
      </form>

      {id !== null && (
        <button className="btn btn--danger btn--block" style={{ marginTop: 24 }} disabled={saving} onClick={remove}>
          Удалить товар
        </button>
      )}
    </div>
  );
}
