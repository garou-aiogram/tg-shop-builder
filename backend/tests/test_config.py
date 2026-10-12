import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.config import load_settings

BASE = {
    "BUILDER_BOT_TOKEN": "123:abc",
    "PUBLIC_URL": "https://shop.example.com/",
    "DATABASE_URL": "postgresql+asyncpg://u:p@db:5432/shop",
    "FERNET_KEY": Fernet.generate_key().decode(),
    "WEBHOOK_SECRET": "s",
}


def test_loads_and_normalizes():
    s = load_settings(BASE)
    assert s.public_url == "https://shop.example.com"


def test_secrets_hidden_in_repr():
    s = load_settings(BASE)
    assert "123:abc" not in repr(s) and "123:abc" not in str(s.model_dump())


@pytest.mark.parametrize("key,value", [("PUBLIC_URL", "http://insecure"), ("DATABASE_URL", "postgresql://u:p@db/x"), ("FERNET_KEY", "not-a-key")])
def test_rejects_bad_values(key, value):
    with pytest.raises(ValidationError):
        load_settings({**BASE, key: value})


def test_missing_secret_fails():
    env = dict(BASE)
    del env["FERNET_KEY"]
    with pytest.raises(ValidationError):
        load_settings(env)
