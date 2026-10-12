"""Этап 2: шифрование токенов, секреты вебхуков, вычистка токенов из логов."""
import logging

import pytest
from cryptography.fernet import Fernet

from app.logging_setup import RedactingFormatter, SkipHealthcheck, redact
from app.security.crypto import TokenCipher, TokenDecryptError
from app.security.webhook import builder_webhook_secret, secrets_equal, shop_webhook_secret

TOKEN = "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"


# ── шифрование ──

def test_encrypt_decrypt_roundtrip(cipher):
    enc = cipher.encrypt(TOKEN)
    assert cipher.decrypt(enc) == TOKEN


def test_ciphertext_does_not_contain_token(cipher):
    enc = cipher.encrypt(TOKEN)
    assert TOKEN not in enc and "AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw" not in enc


def test_encryption_is_randomized(cipher):
    # одинаковые токены → разные шифротексты (случайный IV): по БД нельзя понять, что боты совпадают
    assert cipher.encrypt(TOKEN) != cipher.encrypt(TOKEN)


def test_wrong_key_cannot_decrypt(cipher):
    other = TokenCipher(Fernet.generate_key().decode())
    with pytest.raises(TokenDecryptError):
        other.decrypt(cipher.encrypt(TOKEN))


def test_tampered_ciphertext_rejected(cipher):
    enc = cipher.encrypt(TOKEN)
    tampered = enc[:-5] + ("A" if enc[-5] != "A" else "B") + enc[-4:]
    with pytest.raises(TokenDecryptError):
        cipher.decrypt(tampered)


def test_invalid_key_rejected():
    with pytest.raises(ValueError):
        TokenCipher("not-a-fernet-key")


# ── секреты вебхуков ──

def test_webhook_secrets_deterministic_and_distinct():
    assert shop_webhook_secret("m", 1) == shop_webhook_secret("m", 1)
    assert shop_webhook_secret("m", 1) != shop_webhook_secret("m", 2)
    assert shop_webhook_secret("m", 1) != builder_webhook_secret("m")
    assert shop_webhook_secret("m", 1) != shop_webhook_secret("other-master", 1)


def test_webhook_secret_telegram_charset():
    s = shop_webhook_secret("master", 42)
    assert 1 <= len(s) <= 256 and all(c in "0123456789abcdef" for c in s)


@pytest.mark.parametrize("received,ok", [("abc", True), ("abd", False), (None, False), ("", False)])
def test_secrets_equal(received, ok):
    assert secrets_equal(received, "abc") is ok


# ── логи ──

def test_redact_token():
    assert redact(f"POST https://api.telegram.org/bot{TOKEN}/getMe failed") == (
        "POST https://api.telegram.org/bot<bot-token>/getMe failed"
    )


def test_formatter_redacts_messages_and_tracebacks():
    fmt = RedactingFormatter("%(message)s")
    try:
        raise RuntimeError(f"boom {TOKEN}")
    except RuntimeError:
        import sys

        record = logging.LogRecord("x", logging.ERROR, __file__, 1, "token=%s", (TOKEN,), sys.exc_info())
    out = fmt.format(record)
    assert TOKEN not in out and out.count("<bot-token>") == 2


def test_healthcheck_filtered_from_access_log():
    f = SkipHealthcheck()
    mk = lambda path: logging.LogRecord("uvicorn.access", 20, "", 0, '%s "%s %s"', ("1.2.3.4", "GET", path), None)
    assert f.filter(mk("/api/health")) is False
    assert f.filter(mk("/api/products")) is True
