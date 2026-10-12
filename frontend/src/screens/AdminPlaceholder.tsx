import { useApp } from "../lib/store";
import { useBackButton, useMainButton } from "../lib/tg";
import { Empty } from "../components/ui";

// Раздел администратора — этап 6. Кнопка видна только тем, кого сервер признал админом.
export function AdminPlaceholder() {
  const { nav } = useApp();
  useBackButton(nav.back);
  useMainButton(null);
  return <div className="page"><Empty icon="⚙️" title="Админка" text="Управление товарами, категориями и заказами появится на следующем этапе." /></div>;
}
