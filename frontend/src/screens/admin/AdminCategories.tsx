import { useEffect, useState } from "react";
import { adminApi, api, ApiError, type Category } from "../../lib/api";
import { alert, confirm, haptic, useMainButton } from "../../lib/tg";
import { Empty, ErrorBox, Spinner } from "../../components/ui";

export function AdminCategories() {
  const [items, setItems] = useState<Category[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [editing, setEditing] = useState<{ id: number; name: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () => api.categories().then(setItems).catch((e) => setError(e instanceof ApiError ? e.message : "Ошибка"));
  useEffect(() => { void load(); }, []);
  useMainButton(null);

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try { await fn(); await load(); haptic.tap(); }
    catch (e) { haptic.error(); await alert(e instanceof ApiError ? e.message : "Ошибка"); }
    finally { setBusy(false); }
  };

  const add = () => {
    const name = newName.trim();
    if (!name || !items) return;
    const order = items.length ? Math.max(...items.map((c) => c.sort_order)) + 1 : 0;
    void run(async () => { await adminApi.createCategory(name, order); setNewName(""); });
  };

  const rename = () => {
    if (!editing || !editing.name.trim()) return;
    void run(async () => { await adminApi.updateCategory(editing.id, { name: editing.name.trim() }); setEditing(null); });
  };

  // Порядок: меняем sort_order у соседей. Перед этим нормализуем 0..n-1 — на случай одинаковых значений
  const move = (index: number, dir: -1 | 1) => {
    if (!items) return;
    const j = index + dir;
    if (j < 0 || j >= items.length) return;
    const ordered = [...items];
    [ordered[index], ordered[j]] = [ordered[j], ordered[index]];
    void run(() => Promise.all(
      ordered.map((c, i) => (c.sort_order === i ? null : adminApi.updateCategory(c.id, { sort_order: i }))).filter(Boolean),
    ));
  };

  const remove = async (c: Category) => {
    if (await confirm(`Удалить категорию «${c.name}»? Товары останутся — без категории.`)) {
      void run(() => adminApi.deleteCategory(c.id));
    }
  };

  if (error) return <ErrorBox message={error} onRetry={() => void load()} />;
  if (!items) return <Spinner />;

  return (
    <>
      <form className="inline-add" onSubmit={(e) => { e.preventDefault(); add(); }}>
        <input placeholder="Новая категория" maxLength={64} value={newName} onChange={(e) => setNewName(e.target.value)} />
        <button className="btn btn--primary" disabled={busy || !newName.trim()}>Добавить</button>
      </form>

      {items.length === 0 ? (
        <Empty icon="🗂" title="Категорий пока нет" text="Категории помогают покупателям быстрее найти товар" />
      ) : (
        <ul className="list">
          {items.map((c, i) => (
            <li key={c.id} className="cat">
              {editing?.id === c.id ? (
                <form className="cat__edit" onSubmit={(e) => { e.preventDefault(); rename(); }}>
                  <input autoFocus maxLength={64} value={editing.name} onChange={(e) => setEditing({ id: c.id, name: e.target.value })} />
                  <button className="link" disabled={busy}>Готово</button>
                  <button type="button" className="link" onClick={() => setEditing(null)}>Отмена</button>
                </form>
              ) : (
                <>
                  <span className="cat__name">{c.name}</span>
                  <span className="cat__actions">
                    <button aria-label="Выше" disabled={busy || i === 0} onClick={() => move(i, -1)}>↑</button>
                    <button aria-label="Ниже" disabled={busy || i === items.length - 1} onClick={() => move(i, 1)}>↓</button>
                    <button aria-label="Переименовать" disabled={busy} onClick={() => setEditing({ id: c.id, name: c.name })}>✏️</button>
                    <button aria-label="Удалить" disabled={busy} onClick={() => void remove(c)}>🗑</button>
                  </span>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
