import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import Lab, Machine, Software, User
from app.power import WakeError
from app.security import hash_password

SECRET = "0123456789abcdef0123456789abcdef"


class FakeWaker:
    def __init__(self):
        self.calls: list[str] = []
        self.fail = False

    def wake(self, machine):
        self.calls.append(machine.name)
        if self.fail:
            raise WakeError("relay down")


class FakeProber:
    def __init__(self):
        self.online: set[str] = set()

    def probe(self, machines):
        return {m.id: m.name in self.online for m in machines}


@pytest.fixture
def settings(tmp_path):
    return Settings(
        database_url=f"sqlite:///{tmp_path}/test.db",
        jwt_secret="test",
        cookie_secure=False,
        guac_json_secret_key=SECRET,
        scheduler_enabled=False,
        _env_file=None,
    )


@pytest.fixture
def waker():
    return FakeWaker()


@pytest.fixture
def prober():
    return FakeProber()


@pytest.fixture
def app(settings, waker, prober):
    app = create_app(settings, waker=waker, prober=prober)
    app.state.db.create_all()
    return app


@pytest.fixture
def db(app):
    s = app.state.db.SessionLocal()
    yield s
    s.close()


@pytest.fixture
def seed(db):
    """실습실 1개, PC 3대(PC1,PC2 에 Revit / PC3 에 MIDAS), 학생 2명, 관리자 1명."""
    lab = Lab(name="301호", broadcast_address="10.0.0.255", wol_relay_url="http://relay:8080")
    revit = Software(name="Revit", license_limit=2)
    midas = Software(name="MIDAS")
    pcs = [
        Machine(lab=lab, name="PC1", hostname="10.0.0.1", mac="AA:00:00:00:00:01", software=[revit]),
        Machine(lab=lab, name="PC2", hostname="10.0.0.2", mac="AA:00:00:00:00:02", software=[revit]),
        Machine(lab=lab, name="PC3", hostname="10.0.0.3", mac="AA:00:00:00:00:03", software=[midas]),
    ]
    users = [
        User(username="s1", display_name="학생1", password_hash=hash_password("password1")),
        User(username="s2", display_name="학생2", password_hash=hash_password("password2")),
        User(username="s3", display_name="학생3", password_hash=hash_password("password3")),
        User(username="admin", role="admin", password_hash=hash_password("adminpass")),
    ]
    db.add_all([lab, revit, midas, *pcs, *users])
    db.commit()
    return {"lab": lab, "revit": revit, "midas": midas, "pcs": pcs, "users": users}


def login(app, username, password) -> TestClient:
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return c
