from datetime import timedelta

from fastapi.testclient import TestClient

from app.allocator import tick
from app.db import utcnow
from app.guacamole import decrypt_auth_payload
from app.models import Machine, RemoteSession

from .conftest import SECRET, login


def run_tick(app, prober, waker, now=None):
    db = app.state.db.SessionLocal()
    try:
        tick(db, app.state.settings, prober, waker, now or utcnow())
    finally:
        db.close()


def test_login_and_me(app, seed):
    c = login(app, "s1", "password1")
    assert c.get("/api/auth/me").json()["username"] == "s1"
    assert TestClient(app).get("/api/auth/me").status_code == 401


def test_login_lockout(app, seed):
    c = TestClient(app)
    for _ in range(10):
        assert c.post("/api/auth/login", json={"username": "s1", "password": "x"}).status_code == 401
    assert c.post("/api/auth/login", json={"username": "s1", "password": "password1"}).status_code == 429


def test_online_machine_is_ready_immediately_and_connect(app, seed, prober, waker):
    prober.online = {"PC1", "PC2"}
    run_tick(app, prober, waker)

    c = login(app, "s1", "password1")
    r = c.post("/api/sessions", json={"software_id": seed["revit"].id})
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["status"] == "ready"
    assert s["machine_name"] in {"PC1", "PC2"}
    assert waker.calls == []

    r = c.post(f"/api/sessions/{s['id']}/connect")
    assert r.status_code == 200
    payload = decrypt_auth_payload(SECRET, r.json()["data"])
    conn = payload["connections"][s["machine_name"]]
    assert conn["protocol"] == "rdp"
    assert conn["parameters"]["hostname"].startswith("10.0.0.")
    assert payload["username"] == "jarion:s1"

    # 한 사람은 한 대만
    assert c.post("/api/sessions", json={"software_id": seed["revit"].id}).status_code == 409


def test_offline_machine_wakes_then_ready(app, seed, prober, waker):
    c = login(app, "s1", "password1")
    s = c.post("/api/sessions", json={"software_id": seed["midas"].id}).json()
    assert s["status"] == "waking"
    assert s["machine_name"] == "PC3"
    assert waker.calls == ["PC3"]
    assert c.post(f"/api/sessions/{s['id']}/connect").status_code == 409

    now = utcnow()
    run_tick(app, prober, waker, now + timedelta(seconds=30))
    assert c.get("/api/sessions/current").json()["session"]["status"] == "waking"

    # 재전송
    run_tick(app, prober, waker, now + timedelta(seconds=100))
    assert waker.calls == ["PC3", "PC3"]

    prober.online = {"PC3"}
    run_tick(app, prober, waker, now + timedelta(seconds=120))
    cur = c.get("/api/sessions/current").json()["session"]
    assert cur["status"] == "ready"
    assert cur["expires_at"] is not None


def test_boot_timeout_fails_and_cools_down_machine(app, seed, prober, waker, db):
    c = login(app, "s1", "password1")
    s = c.post("/api/sessions", json={"software_id": seed["midas"].id}).json()
    run_tick(app, prober, waker, utcnow() + timedelta(seconds=400))

    body = c.get("/api/sessions/current").json()
    assert body["session"] is None
    assert body["last"]["status"] == "failed"
    assert body["last"]["end_reason"] == "boot_timeout"

    # 실패한 PC 는 잠시 후보에서 제외 -> MIDAS 가능한 PC 없음
    r = c.post("/api/sessions", json={"software_id": seed["midas"].id})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "no_machine"
    pc3 = db.get(Machine, s and seed["pcs"][2].id)
    db.refresh(pc3)
    assert pc3.wake_failures == 1


def test_license_limit(app, seed, prober, waker):
    seed_revit = seed["revit"].id
    prober.online = {"PC1", "PC2"}
    run_tick(app, prober, waker)
    # Revit 라이선스 2개, Revit PC 2대 -> 3번째 학생은 라이선스 초과
    db = app.state.db.SessionLocal()
    from app.models import Software
    db.get(Software, seed_revit).license_limit = 1
    db.commit()
    db.close()

    assert login(app, "s1", "password1").post("/api/sessions", json={"software_id": seed_revit}).status_code == 201
    r = login(app, "s2", "password2").post("/api/sessions", json={"software_id": seed_revit})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "license_full"


def test_no_show_and_expiry(app, seed, prober, waker):
    prober.online = {"PC1", "PC2", "PC3"}
    run_tick(app, prober, waker)
    c1 = login(app, "s1", "password1")
    c2 = login(app, "s2", "password2")
    s1 = c1.post("/api/sessions", json={"software_id": seed["revit"].id}).json()
    s2 = c2.post("/api/sessions", json={"software_id": seed["revit"].id}).json()
    assert {s1["machine_name"], s2["machine_name"]} == {"PC1", "PC2"}
    c2.post(f"/api/sessions/{s2['id']}/connect")

    now = utcnow()
    run_tick(app, prober, waker, now + timedelta(minutes=16))
    assert c1.get("/api/sessions/current").json()["last"]["end_reason"] == "no_show"
    assert c2.get("/api/sessions/current").json()["session"]["status"] == "ready"

    run_tick(app, prober, waker, now + timedelta(minutes=241))
    assert c2.get("/api/sessions/current").json()["last"]["end_reason"] == "expired"


def test_user_end_frees_machine(app, seed, prober, waker):
    prober.online = {"PC3"}
    run_tick(app, prober, waker)
    c1 = login(app, "s1", "password1")
    s = c1.post("/api/sessions", json={"software_id": seed["midas"].id}).json()
    c2 = login(app, "s2", "password2")
    assert c2.post("/api/sessions", json={"software_id": seed["midas"].id}).status_code == 409
    assert c1.post(f"/api/sessions/{s['id']}/end").json()["status"] == "ended"
    assert c2.post("/api/sessions", json={"software_id": seed["midas"].id}).status_code == 201


def test_cannot_touch_other_users_session(app, seed, prober, waker):
    prober.online = {"PC3"}
    run_tick(app, prober, waker)
    s = login(app, "s1", "password1").post("/api/sessions", json={"software_id": seed["midas"].id}).json()
    c2 = login(app, "s2", "password2")
    assert c2.post(f"/api/sessions/{s['id']}/connect").status_code == 404
    assert c2.post(f"/api/sessions/{s['id']}/end").status_code == 404


def test_wake_error_is_logged_not_fatal(app, seed, prober, waker):
    waker.fail = True
    c = login(app, "s1", "password1")
    r = c.post("/api/sessions", json={"software_id": seed["midas"].id})
    assert r.status_code == 201
    assert r.json()["status"] == "waking"
    admin = login(app, "admin", "adminpass")
    actions = [a["action"] for a in admin.get("/api/admin/audit").json()]
    assert "wake_error" in actions


def test_catalog(app, seed, prober, waker):
    prober.online = {"PC1"}
    run_tick(app, prober, waker)
    c = login(app, "s1", "password1")
    cat = {s["name"]: s for s in c.get("/api/catalog").json()["software"]}
    assert cat["Revit"]["available_now"] == 1
    assert cat["Revit"]["wakeable"] == 1
    assert cat["MIDAS"]["wakeable"] == 1
    c.post("/api/sessions", json={"software_id": seed["revit"].id})
    cat = {s["name"]: s for s in c.get("/api/catalog").json()["software"]}
    assert cat["Revit"]["in_use"] == 1
    assert cat["Revit"]["license_in_use"] == 1


def test_admin_permissions_and_import(app, seed):
    assert login(app, "s1", "password1").get("/api/admin/machines").status_code == 403
    admin = login(app, "admin", "adminpass")
    csv_text = (
        "﻿\"ComputerName\",\"MAC\",\"IPv4\",\"NIC\",\"GPU\",\"Software\",\"Collected\"\n"
        "\"PC4\",\"BB:00:00:00:00:04\",\"10.0.0.4\",\"Intel\",\"RTX 3060\",\"Autodesk Revit 2025; midas Civil\",\"2026-11-01\"\n"
        "\"PC1\",\"AA:00:00:00:00:01\",\"10.0.0.11\",\"Intel\",\"\",\"\",\"2026-11-01\"\n"
        "\"PC5\",\"\",\"\",\"\",\"\",\"\",\"\"\n"
    )
    r = admin.post("/api/admin/machines/import", json={"lab_id": seed["lab"].id, "csv": csv_text})
    assert r.status_code == 200, r.text
    assert r.json()["created"] == ["PC4"]
    assert r.json()["updated"] == ["PC1"]
    assert len(r.json()["skipped"]) == 1
    machines = {m["name"]: m for m in admin.get("/api/admin/machines").json()}
    assert {s["name"] for s in machines["PC4"]["software"]} == {"Revit", "MIDAS"}
    assert machines["PC1"]["hostname"] == "10.0.0.11"


def test_admin_force_end_and_disable(app, seed, prober, waker):
    prober.online = {"PC3"}
    run_tick(app, prober, waker)
    s = login(app, "s1", "password1").post("/api/sessions", json={"software_id": seed["midas"].id}).json()
    admin = login(app, "admin", "adminpass")
    assert len(admin.get("/api/admin/sessions").json()) == 1
    assert admin.post(f"/api/admin/sessions/{s['id']}/end").json()["end_reason"] == "admin"
    pc3 = seed["pcs"][2].id
    assert admin.patch(f"/api/admin/machines/{pc3}", json={"enabled": False}).json()["enabled"] is False
    r = login(app, "s2", "password2").post("/api/sessions", json={"software_id": seed["midas"].id})
    assert r.json()["detail"]["code"] == "no_machine"


def test_open_session_unique_index(app, seed, db):
    """같은 PC 에 열린 세션이 두 개 생기지 않도록 DB 가 막는지."""
    import pytest
    from sqlalchemy.exc import IntegrityError

    u1, u2 = seed["users"][0], seed["users"][1]
    pc = seed["pcs"][0]
    db.add(RemoteSession(user_id=u1.id, machine_id=pc.id, status="ready"))
    db.commit()
    db.add(RemoteSession(user_id=u2.id, machine_id=pc.id, status="waking"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.add(RemoteSession(user_id=u2.id, machine_id=pc.id, status="ended"))
    db.commit()
