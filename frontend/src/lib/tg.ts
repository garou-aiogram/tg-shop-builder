import { useEffect, useRef } from "react";

export const tg: TelegramWebApp | undefined = window.Telegram?.WebApp;

/** Mini App открыт внутри Telegram (есть подписанные данные пользователя). */
export const insideTelegram = Boolean(tg?.initData);

export function initTelegram(): void {
  if (!tg) return;
  tg.ready();
  tg.expand();
  // Чтобы прокрутка каталога вниз не сворачивала Mini App (Bot API 7.7+)
  if (tg.isVersionAtLeast("7.7")) tg.disableVerticalSwipes?.();
}

export const haptic = {
  tap: () => tg?.HapticFeedback?.impactOccurred("light"),
  select: () => tg?.HapticFeedback?.selectionChanged(),
  success: () => tg?.HapticFeedback?.notificationOccurred("success"),
  error: () => tg?.HapticFeedback?.notificationOccurred("error"),
};

export function alert(message: string): Promise<void> {
  return new Promise((resolve) => {
    if (tg && tg.isVersionAtLeast("6.2")) tg.showAlert(message, () => resolve());
    else {
      window.alert(message);
      resolve();
    }
  });
}

export function confirm(message: string): Promise<boolean> {
  return new Promise((resolve) => {
    if (tg && tg.isVersionAtLeast("6.2")) tg.showConfirm(message, resolve);
    else resolve(window.confirm(message));
  });
}

export interface MainButtonOptions {
  text: string;
  onClick: () => void;
  visible?: boolean;
  disabled?: boolean;
  progress?: boolean;
}

/**
 * Нативная нижняя кнопка Telegram (MainButton).
 * Обработчик хранится в ref: смена onClick не пересоздаёт подписку.
 */
export function useMainButton(opts: MainButtonOptions | null): void {
  const handler = useRef<() => void>(() => {});
  handler.current = opts?.onClick ?? (() => {});

  useEffect(() => {
    if (!tg) return;
    const cb = () => handler.current();
    tg.MainButton.onClick(cb);
    return () => {
      tg.MainButton.offClick(cb);
    };
  }, []);

  const visible = Boolean(opts && opts.visible !== false);
  const text = opts?.text ?? "";
  const disabled = Boolean(opts?.disabled);
  const progress = Boolean(opts?.progress);

  useEffect(() => {
    if (!tg) return;
    const mb = tg.MainButton;
    if (!visible) {
      mb.hide();
      return;
    }
    mb.setParams({ text, is_active: !disabled && !progress, is_visible: true });
    if (progress) mb.showProgress(false);
    else mb.hideProgress();
  }, [visible, text, disabled, progress]);

  useEffect(() => () => {
    tg?.MainButton.hide();
  }, []);
}

/** Нативная кнопка «Назад» в шапке Telegram. null — скрыть. */
export function useBackButton(onBack: (() => void) | null): void {
  const handler = useRef<(() => void) | null>(onBack);
  handler.current = onBack;
  const visible = onBack !== null;

  useEffect(() => {
    if (!tg) return;
    const cb = () => handler.current?.();
    tg.BackButton.onClick(cb);
    return () => {
      tg.BackButton.offClick(cb);
    };
  }, []);

  useEffect(() => {
    if (!tg) return;
    if (visible) tg.BackButton.show();
    else tg.BackButton.hide();
  }, [visible]);
}
