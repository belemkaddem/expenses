import os
import tempfile
from datetime import date

os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")
os.environ["USERS"] = "Yassine|0611111111|pass1;Sara|0622222222|pass2"
os.environ["WEBHOOK_TOKEN"] = "tok"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.parser import normalize_phone, parse_sms  # noqa: E402

T = date(2026, 11, 15)


def test_parse_basic():
    c = parse_sms("45 café", T)
    assert (c.kind, c.amount, c.description, c.category) == ("expense", 45, "café", "Restaurant & Café")
    c = parse_sms("Courses Marjane 320,50dh", T)
    assert c.amount == 320.5 and c.category == "Alimentation" and c.description == "Courses Marjane"
    c = parse_sms("60 taxi hier", T)
    assert c.spent_on == date(2026, 11, 14) and c.category == "Transport"
    c = parse_sms("150 cadeau maman #sante", T)
    assert c.category == "Santé"
    c = parse_sms("200 loyer 01/11", T)
    assert c.spent_on == date(2026, 11, 1) and c.amount == 200 and c.category == "Logement"


def test_parse_commands():
    assert parse_sms("TOTAL", T).kind == "total"
    assert parse_sms("total foyer", T).kind == "total_all"
    assert parse_sms("Annuler", T).kind == "undo"
    assert parse_sms("bonjour", T).kind == "unknown"


def test_phone():
    assert normalize_phone("06 11 11 11 11") == "+212611111111"
    assert normalize_phone("00212611111111") == "+212611111111"


def gw(sender, text, mid):
    return {"event": "sms:received", "id": mid,
            "payload": {"messageId": mid, "message": text, "phoneNumber": sender,
                        "receivedAt": "2026-11-15T10:00:00+00:00"}}


def test_webhook_flow():
    with TestClient(app) as client:
        assert client.post("/webhook/sms?token=bad", json=gw("+212611111111", "45 cafe", "a")).status_code == 403
        r = client.post("/webhook/sms?token=tok", json=gw("+212611111111", "45 cafe", "m1")).json()
        assert r["user"] == "Yassine" and "45 DH" in r["reply"]
        # doublon ignoré
        assert client.post("/webhook/sms?token=tok", json=gw("+212611111111", "45 cafe", "m1")).json()["ignored"] == "doublon"
        # numéro inconnu ignoré
        assert "ignored" in client.post("/webhook/sms?token=tok", json=gw("+212699999999", "10 x", "m2")).json()
        client.post("/webhook/sms?token=tok", json=gw("0622222222", "100 essence", "m3"))
        r = client.post("/webhook/sms?token=tok", json=gw("+212611111111", "total foyer", "m4")).json()
        assert "145 DH" in r["reply"]
        r = client.post("/webhook/sms?token=tok", json=gw("+212611111111", "annuler", "m5")).json()
        assert "Supprime" in r["reply"]

        # web
        assert client.get("/", follow_redirects=False).status_code == 303
        client.post("/login", data={"name": "Sara", "password": "pass2"})
        page = client.get("/").text
        assert "100 DH" in page and "essence" in page
        client.post("/expenses", data={"amount": "30", "description": "pharmacie", "user": "Sara"})
        assert "pharmacie" in client.get("/?who=Sara").text
        assert "pharmacie" in client.get("/export.csv").text
        assert "Simulateur" in client.get("/simulateur").text


def test_security():
    from app import main
    main._FAILS.clear()
    with TestClient(app) as client:
        r = client.get("/login")
        assert r.headers["X-Frame-Options"] == "DENY" and "frame-ancestors" in r.headers["Content-Security-Policy"]
        assert client.get("/docs").status_code == 404 and client.get("/openapi.json").status_code == 404
        for _ in range(5):
            client.post("/login", data={"name": "Sara", "password": "wrong"}, follow_redirects=False)
        # even the right password is blocked after 5 failures
        r = client.post("/login", data={"name": "Sara", "password": "pass2"}, follow_redirects=False)
        assert r.headers["location"] == "/login?error=2"
        assert client.get("/", follow_redirects=False).status_code == 303
        assert client.post("/webhook/sms?token=tok", content=b"not json").status_code == 400
    main._FAILS.clear()


def test_production_refuses_weak_config(monkeypatch):
    import pytest
    from app import config
    monkeypatch.setattr(config, "PRODUCTION", True)
    with pytest.raises(RuntimeError) as e:
        config.check_production_config()
    msg = str(e.value)
    assert "trop court" in msg and "WEBHOOK_TOKEN" in msg and "SECRET_KEY" in msg
