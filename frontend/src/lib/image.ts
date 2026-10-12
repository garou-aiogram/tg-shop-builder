/**
 * Фото с телефона бывают по 5–12 МБ и 4000px — сервер принимает до 5 МБ.
 * Уменьшаем на клиенте (canvas, без библиотек): длинная сторона ≤ 1600px, JPEG 85%.
 * Маленькие JPEG/PNG/WebP отправляем как есть, без перекодирования.
 */
const MAX_SIDE = 1600;
const KEEP_AS_IS_BYTES = 1.5 * 1024 * 1024;
const ACCEPTED = ["image/jpeg", "image/png", "image/webp"];

export const IMAGE_ACCEPT = ACCEPTED.join(","); // iOS сам сконвертирует HEIC в JPEG

export async function prepareImage(file: File): Promise<{ blob: Blob; name: string }> {
  if (!file.type.startsWith("image/")) throw new Error("Выберите изображение");
  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    throw new Error("Не удалось прочитать изображение. Поддерживаются JPEG, PNG и WebP.");
  }
  const { width, height } = bitmap;
  const small = Math.max(width, height) <= MAX_SIDE && file.size <= KEEP_AS_IS_BYTES;
  if (small && ACCEPTED.includes(file.type)) {
    bitmap.close();
    return { blob: file, name: file.name };
  }
  const scale = Math.min(1, MAX_SIDE / Math.max(width, height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);
  const ctx = canvas.getContext("2d")!;
  ctx.fillStyle = "#fff"; // прозрачный PNG → белый фон, а не чёрный
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  const blob = await new Promise<Blob | null>((r) => canvas.toBlob(r, "image/jpeg", 0.85));
  if (!blob) throw new Error("Не удалось обработать изображение");
  return { blob, name: "photo.jpg" };
}
