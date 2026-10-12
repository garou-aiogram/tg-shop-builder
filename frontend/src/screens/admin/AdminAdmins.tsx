import { useEffect, useState } from "react";
import { adminApi, ApiError, type AdminInfo, type Invite } from "../../lib/api";
import { dateTime } from "../../lib/format";
import { alert, confirm, haptic, tg, useMainButton } from "../../lib/tg";
import { ErrorBox, Spinner } from "../../components/ui";

/** Только для главного админа (вкладка скрыта у остальных, сервер всё равно проверяет). */
export function AdminAdmins() {
  const [admins, setAdmins] = useState<AdminInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newId, setNewId] = useState("");
  const [invite, setInvite] = useState<Invite | null>(null);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = () => adminApi.admins().then(setAdmins).catch((e) => setError(e instanceof ApiError ? e.message : "Ошибка"));
  useEffect(() => { void load(); }, []);
  useMainButton(null);

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try { await fn(); haptic.success(); }
    catch (e) { haptic.error(); await alert(e instanceof ApiError ? e.message : "Ошибка"); }
    finally { setBusy(false); }
  };

  const addById = () => {
    const id = Number(newId.trim());
    if (!Number.isInteger(id) || id <= 0) { void alert("Telegram ID — это число, например 123456789"); return; }
    void run(async () => { await adminApi.addAdmin(id); setNewId(""); await load(); });
  };

  const remove = async (a: AdminInfo) => {
    const who = a.username ? `@${a.username}` : a.name || `ID ${a.user_id}`;
    if (await confirm(`Убрать ${who} из администраторов?`)) void run(async () => { await adminApi.removeAdmin(a.user_id); await load(); });
  };

  const makeInvite = () => void run(async () => { setInvite(await adminApi.createInvite()); setCopied(false); });

  const copy = async () => {
    if (!invite) return;
    try { await navigator.clipboard.writeText(invite.link); setCopied(true); haptic.tap(); }
    catch { await alert(invite.link); }  // в некоторых клиентах буфер обмена недоступен — покажем ссылку
  };

  const share = () => {
    if (!invite) return;
    const text = "Приглашаю стать администратором магазина. Ссылка одноразовая, действует 24 часа.";
    tg?.openTelegramLink(`https://t.me/share/url?url=${encodeURIComponent(invite.link)}&text=${encodeURIComponent(text)}`);
  };

  if (error) return <ErrorBox message={error} onRetry={() => void load()} />;
  if (!admins) return <Spinner />;

  return (
    <>
      <ul className="list">
        {admins.map((a) => (
          <li key={a.user_id} className="cat">
            <span className="cat__name">
              <span className="admin__name">{a.name || `ID ${a.user_id}`}{a.is_main && <span className="admin__badge">главный</span>}</span>
              <span className="hint">
                {a.username ? `@${a.username}` : a.name ? `ID ${a.user_id}` : "имя появится, когда откроет магазин"}
              </span>
            </span>
            {!a.is_main && <button className="link link--danger" disabled={busy} onClick={() => void remove(a)}>Убрать</button>}
          </li>
        ))}
      </ul>
      <p className="hint" style={{ margin: "8px 4px 20px" }}>
        Администраторы управляют товарами, категориями и заказами и получают уведомления о заказах. Добавлять и убирать администраторов можете только вы.
      </p>

      <h2 className="subtitle" style={{ margin: "0 4px 8px" }}>Пригласить по ссылке</h2>
      {invite ? (
        <div className="invite">
          <code className="invite__link">{invite.link}</code>
          <span className="hint">Одноразовая, действует до {dateTime(invite.expires_at)}. Кто первым откроет её — станет администратором.</span>
          <div className="row">
            <button className="btn btn--primary" onClick={share}>Отправить в Telegram</button>
            <button className="btn btn--secondary" onClick={() => void copy()}>{copied ? "Скопировано ✓" : "Скопировать"}</button>
          </div>
          <button className="link" disabled={busy} onClick={makeInvite}>Создать новую ссылку</button>
        </div>
      ) : (
        <button className="btn btn--secondary btn--block" disabled={busy} onClick={makeInvite}>🔗 Создать ссылку-приглашение</button>
      )}

      <h2 className="subtitle" style={{ margin: "20px 4px 8px" }}>Добавить по Telegram ID</h2>
      <form className="inline-add" onSubmit={(e) => { e.preventDefault(); addById(); }}>
        <input inputMode="numeric" placeholder="Например, 123456789" value={newId} onChange={(e) => setNewId(e.target.value)} />
        <button className="btn btn--primary" disabled={busy || !newId.trim()}>Добавить</button>
      </form>
      <p className="hint" style={{ margin: "0 4px" }}>Свой ID человек может узнать у @userinfobot.</p>
    </>
  );
}
