from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.allocator import tick
from app.db import utcnow
from app.models import AgentCommand, Machine

from .conftest import login

KEY = "enroll-key-for-tests"


@pytest.fixture
def settings(settings):
    settings.agent_enrollment_key = KEY
    settings.agent_exempt_users = "itadmin"
    return settings


def run_tick(app, prober, waker, now=None):
    db = app.state.db.SessionLocal()
    try:
        tick(db, app.state.settings, prober, waker, now or utcnow())
    finally:
        db.close()


def enroll(app, name="PC1", mac="aa-00-00-00-00-01") -> TestClient:
    c = TestClient(app)
    r = c.post("/api/agent/enroll", json={"enrollment_key": KEY, "computer_name": name,
                                          "macs": ["11:22:33:44:55:66", mac], "version": "0.1.0"})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return c


def beat(agent: TestClient, sessions=(), results=(), processes=()):
    r = agent.post("/api/agent/heartbeat", json={
        "version": "0.1.0", "uptime_seconds": 100, "sessions": list(sessions),
        "results": list(results), "processes": list(processes)})
    assert r.status_code == 200, r.text
    return r.json()


def rdp(user, state="active", sid=2):
    return {"id": sid, "user": user, "domain": "SCHOOL", "state": state, "protocol": "rdp"}


def console(user):
    return {"id": 1, "user": user, "domain": "SCHOOL", "state": "active", "protocol": "console"}


def test_enroll_checks(app, seed):
    c = TestClient(app)
    base = {"computer_name": "PC1", "macs": ["AA:00:00:00:00:01"]}
    assert c.post("/api/agent/enroll", json={**base, "enrollment_key": "wrong"}).status_code == 403
    assert c.post("/api/agent/enroll", json={**base, "enrollment_key": KEY, "computer_name": "NOPE"}).status_code == 404
    assert c.post("/api/agent/enroll", json={**base, "enrollment_key": KEY, "macs": ["AA:00:00:00:00:99"]}).status_code == 403
    # 이름 대소문자 무시
    assert c.post("/api/agent/enroll", json={**base, "enrollment_key": KEY, "computer_name": "pc1"}).status_code == 200
    assert c.post("/api/agent/heartbeat", json={}, headers={"Authorization": "Bearer bad"}).status_code == 401


def test_reenroll_rotates_token(app, seed):
    a1 = enroll(app)
    a2 = enroll(app)
    assert a1.post("/api/agent/heartbeat", json={}).status_code == 401
    assert a2.post("/api/agent/heartbeat", json={}).status_code == 200


def test_console_user_blocks_allocation(app, seed, prober, waker):
    prober.online = {"PC1", "PC2"}
    run_tick(app, prober, waker)
    beat(enroll(app, "PC1", "AA:00:00:00:00:01"), sessions=[console("kim")])
    beat(enroll(app, "PC2", "AA:00:00:00:00:02"), sessions=[console("lee")])
    r = login(app, "s1", "password1").post("/api/sessions", json={"software_id": seed["revit"].id})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "no_machine"


def test_stale_agent_report_is_ignored(app, seed, prober, waker, db):
    prober.online = {"PC1"}
    run_tick(app, prober, waker)
    beat(enroll(app), sessions=[console("kim")])
    pc1 = db.get(Machine, seed["pcs"][0].id)
    pc1.agent_seen_at = utcnow() - timedelta(minutes=5)
    db.commit()
    r = login(app, "s1", "password1").post("/api/sessions", json={"software_id": seed["revit"].id})
    assert r.status_code == 201


def test_full_lifecycle_with_agent(app, seed, prober, waker):
    prober.online = {"PC3"}
    run_tick(app, prober, waker)
    agent = enroll(app, "PC3", "AA:00:00:00:00:03")
    beat(agent)

    student = login(app, "s1", "password1")
    s = student.post("/api/sessions", json={"software_id": seed["midas"].id}).json()
    assert s["machine_name"] == "PC3"

    # 에이전트가 RDP 접속을 보면 접속 시각 기록, 포털 세션이 있으니 로그오프 안 함
    out = beat(agent, sessions=[rdp("s1")], processes=["midas_civil.exe"])
    assert out["commands"] == []
    cur = student.get("/api/sessions/current").json()["session"]
    assert cur["connected_at"] is not None

    # 학생이 반납 -> 바로 로그오프 명령
    student.post(f"/api/sessions/{s['id']}/end")
    out = beat(agent, sessions=[rdp("s1")])
    assert [c["kind"] for c in out["commands"]] == ["logoff"]
    cmd_id = out["commands"][0]["id"]

    # 결과 보고 -> 다시 보내지 않음
    out = beat(agent, results=[{"id": cmd_id, "ok": True}])
    assert out["commands"] == []

    admin = login(app, "admin", "adminpass")
    m = next(x for x in admin.get("/api/admin/machines").json() if x["name"] == "PC3")
    assert m["agent_status"] == "ok"
    assert m["remote_users"] == ""


def test_expiry_warning_then_message_and_delayed_logoff(app, seed, prober, waker):
    prober.online = {"PC3"}
    run_tick(app, prober, waker)
    agent = enroll(app, "PC3", "AA:00:00:00:00:03")
    s = login(app, "s1", "password1").post("/api/sessions", json={"software_id": seed["midas"].id}).json()
    beat(agent, sessions=[rdp("s1")])

    now = utcnow()
    db = app.state.db.SessionLocal()
    m = db.get(Machine, seed["pcs"][2].id)
    m.agent_seen_at = now + timedelta(minutes=232)  # 에이전트가 그 시점에도 살아 있다고 가정
    db.commit()
    db.close()
    run_tick(app, prober, waker, now + timedelta(minutes=232))  # 240분 중 8분 남음 -> 안내
    run_tick(app, prober, waker, now + timedelta(minutes=233))  # 안내는 한 번만
    db = app.state.db.SessionLocal()
    cmds = db.query(AgentCommand).all()
    assert [c.kind for c in cmds] == ["message"]
    assert "남았습니다" in cmds[0].payload
    db.close()

    # 만료 -> 안내 + 60초 뒤 로그오프
    run_tick(app, prober, waker, now + timedelta(minutes=241))
    db = app.state.db.SessionLocal()
    cmds = db.query(AgentCommand).order_by(AgentCommand.id).all()
    assert [c.kind for c in cmds] == ["message", "message", "logoff"]
    assert cmds[2].not_before > cmds[1].not_before
    db.close()


def test_disconnected_too_long_returns_machine(app, seed, prober, waker):
    prober.online = {"PC3"}
    run_tick(app, prober, waker)
    agent = enroll(app, "PC3", "AA:00:00:00:00:03")
    c = login(app, "s1", "password1")
    c.post("/api/sessions", json={"software_id": seed["midas"].id})
    beat(agent, sessions=[rdp("s1")])
    beat(agent, sessions=[rdp("s1", state="disconnected")])

    db = app.state.db.SessionLocal()
    m = db.get(Machine, seed["pcs"][2].id)
    base = m.remote_state_since
    m.agent_seen_at = base + timedelta(minutes=16)
    db.commit()
    db.close()
    run_tick(app, prober, waker, base + timedelta(minutes=16))
    assert c.get("/api/sessions/current").json()["last"]["end_reason"] == "disconnected"


def test_stale_remote_session_cleanup_and_exempt(app, seed, prober, waker):
    agent = enroll(app)
    # IT 관리자 접속은 건드리지 않음
    assert beat(agent, sessions=[rdp("itadmin")])["commands"] == []
    # 포털을 거치지 않은 원격 접속 -> 로그오프
    out = beat(agent, sessions=[rdp("someone")])
    assert [c["kind"] for c in out["commands"]] == ["logoff"]
    # 아직 처리 안 됐으면 중복 생성 안 함
    beat(agent, sessions=[rdp("someone")])
    db = app.state.db.SessionLocal()
    assert db.query(AgentCommand).count() == 1
    db.close()


def test_idle_shutdown(app, seed, prober, waker, settings):
    settings.idle_shutdown_minutes = 30
    prober.online = {"PC1"}
    agent = enroll(app)
    beat(agent)
    db = app.state.db.SessionLocal()
    m = db.get(Machine, seed["pcs"][0].id)
    start = m.idle_since
    m.agent_seen_at = start + timedelta(minutes=31)
    db.commit()
    db.close()
    run_tick(app, prober, waker, start + timedelta(minutes=31))
    db = app.state.db.SessionLocal()
    assert [c.kind for c in db.query(AgentCommand).all()] == ["shutdown"]
    db.close()


def test_admin_logoff_and_revoke(app, seed):
    agent = enroll(app)
    admin = login(app, "admin", "adminpass")
    pc1 = seed["pcs"][0].id
    assert admin.post(f"/api/admin/machines/{pc1}/logoff").status_code == 202
    assert [c["kind"] for c in beat(agent)["commands"]] == ["logoff"]
    assert len(admin.get(f"/api/admin/machines/{pc1}/commands").json()) == 1
    assert admin.delete(f"/api/admin/machines/{pc1}/agent").status_code == 204
    assert agent.post("/api/agent/heartbeat", json={}).status_code == 401
