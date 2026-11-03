"""PC 에이전트용 API.

등록(enroll): 모든 PC 가 같은 등록 키로 한 번 등록하면, 포털에 등록된 같은 이름(+MAC 일치)의
PC 에 전용 토큰이 발급된다. 이후 에이전트는 그 토큰으로 주기 보고(heartbeat)를 보내고,
응답으로 실행할 명령(안내 메시지, 로그오프, 종료)을 받는다. PC 에 들어오는 포트를 열 필요가 없다.
"""
import hashlib
import hmac
import json
import re
import secrets
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import agentcmd
from ..audit import audit
from ..config import Settings
from ..db import utcnow
from ..deps import get_db, get_settings_dep
from ..models import (
    CMD_LOGOFF,
    OPEN_STATUSES,
    READY,
    REMOTE_ACTIVE,
    REMOTE_DISCONNECTED,
    REMOTE_NONE,
    AgentCommand,
    Machine,
    RemoteSession,
)
from ..security import client_ip

router = APIRouter(prefix="/api/agent", tags=["agent"])

REDELIVER_AFTER = timedelta(minutes=2)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _norm_mac(mac: str) -> str:
    return re.sub(r"[^0-9A-F]", "", mac.upper())


# ------------------------------------------------------------------ 등록
class EnrollIn(BaseModel):
    enrollment_key: str = Field(max_length=200)
    computer_name: str = Field(min_length=1, max_length=100)
    macs: list[str] = Field(default_factory=list, max_length=32)
    version: str = Field(default="", max_length=50)


class EnrollOut(BaseModel):
    token: str
    machine_name: str
    interval_seconds: int


@router.post("/enroll", response_model=EnrollOut)
def enroll(body: EnrollIn, request: Request, db: Session = Depends(get_db),
           settings: Settings = Depends(get_settings_dep)):
    ip = client_ip(request)
    if not settings.agent_enrollment_key:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "에이전트 등록이 꺼져 있습니다")
    if not hmac.compare_digest(body.enrollment_key.encode(), settings.agent_enrollment_key.encode()):
        audit(db, "agent_enroll_failed", None, ip=ip, computer=body.computer_name, reason="bad_key")
        db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "등록 키가 올바르지 않습니다")

    m = db.scalar(select(Machine).where(func.lower(Machine.name) == body.computer_name.lower()))
    if m is None:
        audit(db, "agent_enroll_failed", None, ip=ip, computer=body.computer_name, reason="unknown_machine")
        db.commit()
        raise HTTPException(status.HTTP_404_NOT_FOUND, "포털에 등록되지 않은 PC 입니다. 관리 화면에서 먼저 등록하세요")
    if _norm_mac(m.mac) not in {_norm_mac(x) for x in body.macs}:
        audit(db, "agent_enroll_failed", None, ip=ip, computer=body.computer_name, reason="mac_mismatch")
        db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "PC 의 MAC 주소가 포털에 등록된 값과 다릅니다")

    token = secrets.token_urlsafe(32)
    m.agent_token_hash = token_hash(token)
    m.agent_version = body.version
    audit(db, "agent_enroll", None, ip=ip, machine=m.name, version=body.version)
    db.commit()
    return EnrollOut(token=token, machine_name=m.name, interval_seconds=settings.agent_interval_seconds)


# ------------------------------------------------------------------ 주기 보고
class WinSession(BaseModel):
    id: int
    user: str = Field(default="", max_length=200)
    domain: str = Field(default="", max_length=200)
    state: Literal["active", "disconnected", "other"] = "other"
    protocol: Literal["console", "rdp", "other"] = "other"
    client_name: str = Field(default="", max_length=200)


class CommandResult(BaseModel):
    id: int
    ok: bool
    error: str = Field(default="", max_length=2000)


class HeartbeatIn(BaseModel):
    version: str = Field(default="", max_length=50)
    uptime_seconds: int = 0
    sessions: list[WinSession] = Field(default_factory=list, max_length=64)
    processes: list[str] = Field(default_factory=list, max_length=64)
    results: list[CommandResult] = Field(default_factory=list, max_length=64)


class CommandOut(BaseModel):
    id: int
    kind: str
    payload: dict


class HeartbeatOut(BaseModel):
    machine_name: str
    interval_seconds: int
    watch_processes: list[str]
    exempt_users: list[str]
    commands: list[CommandOut]


def agent_machine(request: Request, db: Session = Depends(get_db)) -> Machine:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "에이전트 토큰이 필요합니다")
    m = db.scalar(select(Machine).where(Machine.agent_token_hash == token_hash(auth[7:].strip())))
    if m is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "등록되지 않은 에이전트입니다")
    return m


def _split(s: str) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip()]


def _full(s: WinSession) -> str:
    return f"{s.domain}\\{s.user}" if s.domain else s.user


@router.post("/heartbeat", response_model=HeartbeatOut)
def heartbeat(body: HeartbeatIn, db: Session = Depends(get_db),
              settings: Settings = Depends(get_settings_dep), m: Machine = Depends(agent_machine)):
    now = utcnow()
    exempt = {u.lower() for u in _split(settings.agent_exempt_users)}

    def is_exempt(s: WinSession) -> bool:
        return s.user.lower() in exempt or _full(s).lower() in exempt

    # 1) 이전 명령 결과 반영
    for r in body.results:
        cmd = db.get(AgentCommand, r.id)
        if cmd is not None and cmd.machine_id == m.id and cmd.done_at is None:
            cmd.done_at, cmd.ok, cmd.error = now, r.ok, r.error
            if not r.ok:
                audit(db, "agent_command_failed", None, machine=m.name, command=cmd.kind, error=r.error)

    # 2) 상태 갱신
    users = [s for s in body.sessions if s.user]
    console = [s for s in users if s.protocol == "console"]
    remote = [s for s in users if s.protocol == "rdp" and not is_exempt(s)]
    if any(s.state == "active" for s in remote):
        remote_state = REMOTE_ACTIVE
    elif remote:
        remote_state = REMOTE_DISCONNECTED
    else:
        remote_state = REMOTE_NONE
    if remote_state != m.remote_state or m.remote_state_since is None:
        m.remote_state, m.remote_state_since = remote_state, now

    m.agent_seen_at = now
    m.agent_version = body.version
    m.console_user = ", ".join(_full(s) for s in console)[:200]
    m.remote_users = ", ".join(_full(s) for s in remote)[:500]
    m.running = ", ".join(sorted(set(body.processes)))[:500]

    open_session = db.scalar(select(RemoteSession).where(
        RemoteSession.machine_id == m.id, RemoteSession.status.in_(OPEN_STATUSES)))

    if users or open_session:
        m.idle_since = None
    elif m.idle_since is None:
        m.idle_since = now

    # 3) 원격 접속이 실제로 이루어졌으면 접속 시각 기록
    if open_session and open_session.status == READY and remote_state == REMOTE_ACTIVE \
            and open_session.connected_at is None:
        open_session.connected_at = now

    # 4) 포털 세션 없이 남아 있는 원격 세션 정리 (반납 후 남은 세션, 포털을 거치지 않은 접속)
    if remote and open_session is None and not agentcmd.pending(db, m, CMD_LOGOFF):
        agentcmd.queue_logoff(db, m, now)
        audit(db, "agent_stale_remote", None, machine=m.name, users=m.remote_users)

    # 5) 보낼 명령
    cmds = list(db.scalars(
        select(AgentCommand)
        .where(AgentCommand.machine_id == m.id, AgentCommand.done_at.is_(None),
               AgentCommand.not_before <= now)
        .order_by(AgentCommand.id)
    ))
    out = []
    for c in cmds:
        if c.delivered_at is None or now - c.delivered_at >= REDELIVER_AFTER:
            c.delivered_at = now
            out.append(CommandOut(id=c.id, kind=c.kind, payload=json.loads(c.payload or "{}")))

    db.commit()
    return HeartbeatOut(
        machine_name=m.name,
        interval_seconds=settings.agent_interval_seconds,
        watch_processes=_split(settings.agent_watch_processes),
        exempt_users=sorted(exempt),
        commands=out,
    )
