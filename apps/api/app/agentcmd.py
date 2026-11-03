"""에이전트 명령 생성 헬퍼."""
import json
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import CMD_LOGOFF, CMD_MESSAGE, CMD_SHUTDOWN, AgentCommand, Machine, RemoteSession

TITLE = "JARION 원격 실습실"


def queue(db: Session, machine: Machine, kind: str, payload: dict | None = None,
          not_before: datetime | None = None, session: RemoteSession | None = None) -> AgentCommand | None:
    if not machine.has_agent:
        return None
    cmd = AgentCommand(machine=machine, kind=kind, payload=json.dumps(payload or {}, ensure_ascii=False),
                       session_id=session.id if session else None)
    if not_before is not None:
        cmd.not_before = not_before
    db.add(cmd)
    return cmd


def queue_message(db: Session, machine: Machine, text: str, now: datetime,
                  session: RemoteSession | None = None) -> None:
    queue(db, machine, CMD_MESSAGE, {"title": TITLE, "text": text, "target": "remote"}, now, session)


def queue_logoff(db: Session, machine: Machine, now: datetime, delay_seconds: int = 0,
                 session: RemoteSession | None = None) -> None:
    """원격(RDP) 세션만 로그오프한다. 현장(콘솔) 사용자는 건드리지 않는다."""
    queue(db, machine, CMD_LOGOFF, {"target": "remote"}, now + timedelta(seconds=delay_seconds), session)


def queue_shutdown(db: Session, machine: Machine, now: datetime, delay_seconds: int = 60) -> None:
    queue(db, machine, CMD_SHUTDOWN, {"delay_seconds": delay_seconds,
                                      "message": "사용하지 않는 PC 를 절전을 위해 종료합니다."}, now)


def pending(db: Session, machine: Machine, kind: str | None = None) -> list[AgentCommand]:
    q = select(AgentCommand).where(AgentCommand.machine_id == machine.id, AgentCommand.done_at.is_(None))
    if kind:
        q = q.where(AgentCommand.kind == kind)
    return list(db.scalars(q))
