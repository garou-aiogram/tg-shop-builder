"""Шифрование токенов ботов (Fernet = AES-128-CBC + HMAC-SHA256).

Токен в открытом виде существует только в памяти процесса на время
вызова Telegram API. В БД и в FSM-хранилище лежит только шифротекст.
"""
from cryptography.fernet import Fernet, InvalidToken


class TokenDecryptError(Exception):
    """Шифротекст повреждён или зашифрован другим ключом (FERNET_KEY сменили?)."""


class TokenCipher:
    def __init__(self, key: str) -> None:
        # Fernet сам проверяет формат ключа (32 байта в urlsafe-base64) и кидает ValueError
        self._fernet = Fernet(key.encode())

    def encrypt(self, token: str) -> str:
        return self._fernet.encrypt(token.encode()).decode()

    def decrypt(self, data: str) -> str:
        try:
            return self._fernet.decrypt(data.encode()).decode()
        except InvalidToken as e:
            raise TokenDecryptError("не удалось расшифровать токен") from e
