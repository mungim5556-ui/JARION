from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, UTCDateTime, utcnow

# 세션 상태
WAKING = "waking"   # PC 를 켜는 중
READY = "ready"     # 접속 가능
ENDED = "ended"
FAILED = "failed"
OPEN_STATUSES = (WAKING, READY)

# 에이전트가 보고하는 원격(RDP) 세션 상태
REMOTE_NONE = "none"
REMOTE_ACTIVE = "active"
REMOTE_DISCONNECTED = "disconnected"

# 에이전트 명령
CMD_MESSAGE = "message"
CMD_LOGOFF = "logoff"
CMD_SHUTDOWN = "shutdown"
_OPEN_SQL = text("status IN ('waking', 'ready')")

machine_software = Table(
    "machine_software",
    Base.metadata,
    Column("machine_id", ForeignKey("machines.id", ondelete="CASCADE"), primary_key=True),
    Column("software_id", ForeignKey("software.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(100), default="")
    password_hash: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="student")  # student | admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class Lab(Base):
    __tablename__ = "labs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    location: Mapped[str] = mapped_column(String(200), default="")
    # 실습실 VLAN 의 브로드캐스트 주소와, 그 VLAN 안에서 도는 WoL 릴레이 주소
    broadcast_address: Mapped[str] = mapped_column(String(50), default="255.255.255.255")
    wol_relay_url: Mapped[str] = mapped_column(String(300), default="")

    machines: Mapped[list["Machine"]] = relationship(back_populates="lab")


class Software(Base):
    __tablename__ = "software"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    # 동시 사용 가능 라이선스 수 (None = 제한 없음)
    license_limit: Mapped[int | None] = mapped_column(Integer)


class Machine(Base):
    __tablename__ = "machines"

    id: Mapped[int] = mapped_column(primary_key=True)
    lab_id: Mapped[int] = mapped_column(ForeignKey("labs.id"))
    name: Mapped[str] = mapped_column(String(100), unique=True)
    hostname: Mapped[str] = mapped_column(String(200))  # IP 또는 DNS
    mac: Mapped[str] = mapped_column(String(17))
    rdp_port: Mapped[int] = mapped_column(Integer, default=3389)
    gpu: Mapped[str] = mapped_column(String(200), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # 상태 (스케줄러가 갱신)
    online: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_probe_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    wake_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_wake_failure_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    # PC 에이전트 (agent/) 가 보고하는 상태
    agent_token_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    agent_version: Mapped[str] = mapped_column(String(50), default="")
    agent_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    console_user: Mapped[str] = mapped_column(String(200), default="")   # 현장(콘솔)에 로그인한 사람
    remote_users: Mapped[str] = mapped_column(String(500), default="")   # 원격(RDP) 로그인 사용자, 쉼표 구분
    remote_state: Mapped[str] = mapped_column(String(20), default=REMOTE_NONE)
    remote_state_since: Mapped[datetime | None] = mapped_column(UTCDateTime)
    running: Mapped[str] = mapped_column(String(500), default="")        # 감시 대상 프로그램 실행 현황
    idle_since: Mapped[datetime | None] = mapped_column(UTCDateTime)     # 아무도 안 쓰기 시작한 시각

    lab: Mapped[Lab] = relationship(back_populates="machines")
    software: Mapped[list[Software]] = relationship(secondary=machine_software, lazy="selectin")

    @property
    def has_agent(self) -> bool:
        return self.agent_token_hash is not None

    def agent_alive(self, now: datetime, fresh_seconds: int) -> bool:
        return self.agent_seen_at is not None and (now - self.agent_seen_at).total_seconds() <= fresh_seconds

    def occupied_by_others(self, now: datetime, fresh_seconds: int) -> bool:
        """현장 사용자나 포털 밖의 원격 사용자가 있는지 (에이전트 보고가 최신일 때만 판단)."""
        return self.agent_alive(now, fresh_seconds) and bool(self.console_user or self.remote_users)


class RemoteSession(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        # PC 한 대에 열린 세션은 하나, 학생 한 명도 열린 세션은 하나 (동시 배정 경쟁 시 DB 가 막아줌)
        Index("uq_open_session_machine", "machine_id", unique=True,
              sqlite_where=_OPEN_SQL, postgresql_where=_OPEN_SQL),
        Index("uq_open_session_user", "user_id", unique=True,
              sqlite_where=_OPEN_SQL, postgresql_where=_OPEN_SQL),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id"), index=True)
    software_id: Mapped[int | None] = mapped_column(ForeignKey("software.id"))
    status: Mapped[str] = mapped_column(String(20), index=True)
    end_reason: Mapped[str | None] = mapped_column(String(50))

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    wake_sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    wake_attempts: Mapped[int] = mapped_column(Integer, default=0)
    ready_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    connected_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    warned_at: Mapped[datetime | None] = mapped_column(UTCDateTime)  # 종료 임박 안내를 보낸 시각

    user: Mapped[User] = relationship(lazy="joined")
    machine: Mapped[Machine] = relationship(lazy="joined")
    software: Mapped[Software | None] = relationship(lazy="joined")

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES


class AgentCommand(Base):
    """에이전트에게 보낼 명령. 에이전트가 주기 보고(heartbeat) 응답으로 받아 실행하고 결과를 돌려준다."""

    __tablename__ = "agent_commands"

    id: Mapped[int] = mapped_column(primary_key=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("sessions.id"))
    kind: Mapped[str] = mapped_column(String(20))       # message | logoff | shutdown
    payload: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    not_before: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    done_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    ok: Mapped[bool | None] = mapped_column(Boolean)
    error: Mapped[str] = mapped_column(Text, default="")

    machine: Mapped[Machine] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    username: Mapped[str] = mapped_column(String(100), default="")
    action: Mapped[str] = mapped_column(String(50), index=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
