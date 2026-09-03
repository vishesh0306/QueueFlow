import uuid
from unittest.mock import patch

from config import settings
from db.models import Clinic


def _make_clinic(db):
    clinic = Clinic(name="Telegram Connect Test Clinic")
    db.add(clinic)
    db.commit()
    return clinic


def test_telegram_connect_returns_a_start_deep_link_carrying_the_clinic_id(client, db):
    clinic = _make_clinic(db)

    with patch.object(settings, "telegram_bot_username", "queueflow_test_bot"):
        resp = client.get(f"/clinics/{clinic.id}/telegram-connect")

    assert resp.status_code == 200
    assert resp.json()["deep_link"] == f"https://t.me/queueflow_test_bot?start={clinic.id}"


def test_telegram_connect_404s_for_an_unknown_clinic(client, db):
    with patch.object(settings, "telegram_bot_username", "queueflow_test_bot"):
        resp = client.get(f"/clinics/{uuid.uuid4()}/telegram-connect")

    assert resp.status_code == 404


def test_telegram_connect_409s_when_no_bot_is_configured(client, db):
    clinic = _make_clinic(db)

    with patch.object(settings, "telegram_bot_username", ""):
        resp = client.get(f"/clinics/{clinic.id}/telegram-connect")

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "TELEGRAM_NOT_CONFIGURED"
