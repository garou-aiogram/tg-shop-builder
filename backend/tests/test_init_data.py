"""Этап 4: валидация initData (валидная / поддельная подпись и прочие атаки)."""
import json
import time

import pytest

from app.security.init_data import InitDataError, sign_init_data, validate_init_data

TOKEN = "111111111:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
OTHER = "222222222:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
NOW = 1_790_000_000


def fields(uid=42, auth_date=NOW, **extra):
    return {"user": json.dumps({"id": uid, "first_name": "Ann", "username": "ann"}),
            "auth_date": str(auth_date), "query_id": "AAH", **extra}


def test_valid_signature():
    user = validate_init_data(sign_init_data(fields(), TOKEN), TOKEN, now=NOW)
    assert user.id == 42 and user.first_name == "Ann" and user.username == "ann"


def test_signed_by_other_bot_rejected():
    # initData из магазина B не подходит магазину A
    with pytest.raises(InitDataError, match="bad signature"):
        validate_init_data(sign_init_data(fields(), OTHER), TOKEN, now=NOW)


def test_tampered_user_id_rejected():
    raw = sign_init_data(fields(uid=42), TOKEN)
    forged = raw.replace("%22id%22%3A+42", "%22id%22%3A+1")  # подменили id в подписанных данных
    assert forged != raw
    with pytest.raises(InitDataError, match="bad signature"):
        validate_init_data(forged, TOKEN, now=NOW)


def test_forged_hash_rejected():
    raw = sign_init_data(fields(), TOKEN)
    body, _, h = raw.rpartition("hash=")
    with pytest.raises(InitDataError, match="bad signature"):
        validate_init_data(body + "hash=" + "0" * 64, TOKEN, now=NOW)


@pytest.mark.parametrize("raw", ["", "garbage", "user=%7B%7D&auth_date=1", "a=1&a=2&hash=x"])
def test_malformed_rejected(raw):
    with pytest.raises(InitDataError):
        validate_init_data(raw, TOKEN, now=NOW)


def test_expired_rejected():
    raw = sign_init_data(fields(auth_date=NOW - 25 * 3600), TOKEN)
    with pytest.raises(InitDataError, match="expired"):
        validate_init_data(raw, TOKEN, now=NOW)


def test_future_auth_date_rejected():
    raw = sign_init_data(fields(auth_date=NOW + 3600), TOKEN)
    with pytest.raises(InitDataError, match="future"):
        validate_init_data(raw, TOKEN, now=NOW)


def test_missing_user_rejected():
    raw = sign_init_data({"auth_date": str(NOW)}, TOKEN)
    with pytest.raises(InitDataError, match="no user"):
        validate_init_data(raw, TOKEN, now=NOW)


def test_real_clock():
    raw = sign_init_data(fields(auth_date=int(time.time())), TOKEN)
    assert validate_init_data(raw, TOKEN).id == 42
