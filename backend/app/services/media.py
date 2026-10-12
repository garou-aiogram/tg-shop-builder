"""Хранение фото товаров в MEDIA_DIR (volume в docker).

Тип файла определяется по сигнатуре (первым байтам), а не по имени или
Content-Type от клиента: переименованный .html/.svg не пройдёт.
Имя файла генерируется сервером — путь из запроса в ФС не попадает.
"""
from __future__ import annotations

import secrets
from pathlib import Path

MAX_IMAGE_BYTES = 5 * 1024 * 1024

SIGNATURES: list[tuple[bytes, int, str]] = [
    (b"\xff\xd8\xff", 0, "jpg"),
    (b"\x89PNG\r\n\x1a\n", 0, "png"),
    (b"WEBP", 8, "webp"),  # RIFF....WEBP
]


class MediaError(Exception):
    pass


def detect_image_ext(data: bytes) -> str | None:
    for sig, offset, ext in SIGNATURES:
        if data[offset : offset + len(sig)] == sig:
            if ext == "webp" and data[:4] != b"RIFF":
                continue
            return ext
    return None


class MediaStorage:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def save_product_image(self, shop_id: int, data: bytes) -> str:
        if len(data) > MAX_IMAGE_BYTES:
            raise MediaError("Файл больше 5 МБ")
        ext = detect_image_ext(data)
        if ext is None:
            raise MediaError("Поддерживаются только JPEG, PNG и WebP")
        rel = Path("shops") / str(shop_id) / f"{secrets.token_hex(12)}.{ext}"
        dest = self.root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return rel.as_posix()

    def delete(self, rel_path: str | None) -> None:
        if not rel_path:
            return
        path = (self.root / rel_path).resolve()
        # страховка: удаляем только внутри MEDIA_DIR
        if self.root.resolve() in path.parents and path.is_file():
            path.unlink()
