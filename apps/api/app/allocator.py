"""PC 배정과 세션 수명 관리.

배정 순서:
  1. 이미 켜져 있고 비어 있는 PC (가장 오래 안 쓴 것부터) -> 바로 접속 가능(ready)
  2. 꺼져 있는 PC -> WoL 로 켜고(waking), 스케줄러가 RDP 포트가 열리면 ready 로 바꾼다
최근 깨우기에 실패한 PC 는 일정 시간 후보에서 뺀다.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .audit import audit
from .config import Settings
from .models import (
    ENDED,
    FAILED,
    OPEN_STATUSES,
    READY,
    WAKING,
    Machine,
    RemoteSession,
    Software,
    User,
)
from .power import Waker, WakeError

log = logging.getLogger(__name__)

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class AllocationError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def open_session_for(db: Session, user_id: int) -> RemoteSession | None:
    return db.scalar(
        select(RemoteSession).where(
            RemoteSession.user_id == user_id, RemoteSession.status.in_(OPEN_STATUSES)
        )
    )


def busy_machine_ids(db: Session) -> set[int]:
    return set(
        db.scalars(
            select(RemoteSession.machine_id).where(RemoteSession.status.in_(OPEN_STATUSES))
        )
    )


def license_in_use(db: Session, software_id: int) -> int:
    return db.scalar(
        select(func.count()).where(
            RemoteSession.software_id == software_id,
            RemoteSession.status.in_(OPEN_STATUSES),
        )
    ) or 0


def candidate_machines(
    db: Session, settings: Settings, software: Software | None, now: datetime
) -> list[Machine]:
    cooldown_since = now - timedelta(minutes=settings.wake_failure_cooldown_minutes)
    q = select(Machine).where(
        Machine.enabled.is_(True),
        or_(Machine.last_wake_failure_at.is_(None), Machine.last_wake_failure_at < cooldown_since),
    )
    busy = busy_machine_ids(db)
    if busy:
        q = q.where(Machine.id.not_in(busy))
    if software is not None:
        q = q.where(Machine.software.any(Software.id == software.id))
    machines = list(db.scalars(q))

    def lru(m: Machine) -> datetime:
        return m.last_used_at or _EPOCH

    online = sorted((m for m in machines if m.online), key=lru)
    # 꺼진 PC 는 WoL 릴레이가 있는 실습실만, 깨우기 실패가 적은 PC 우선
    offline = sorted(
        (m for m in machines if not m.online and m.lab.wol_relay_url),
        key=lambda m: (m.wake_failures, lru(m)),
    )
    return online + offline


def send_wake(db: Session, session: RemoteSession, waker: Waker, now: datetime) -> None:
    session.wake_sent_at = now
    session.wake_attempts += 1
    try:
        waker.wake(session.machine)
    except WakeError as e:
        log.warning("wake failed for %s: %s", session.machine.name, e)
        audit(db, "wake_error", session.user, session_id=session.id,
              machine=session.machine.name, error=str(e))


def mark_ready(session: RemoteSession, settings: Settings, now: datetime) -> None:
    session.status = READY
    session.ready_at = now
    session.expires_at = now + timedelta(minutes=settings.session_max_minutes)
    session.machine.wake_failures = 0


def end_session(db: Session, session: RemoteSession, reason: str, now: datetime,
                actor: User | None = None, status: str = ENDED) -> None:
    session.status = status
    session.end_reason = reason
    session.ended_at = now
    session.machine.last_used_at = now
    audit(db, "session_end" if status == ENDED else "session_failed", actor or session.user,
          session_id=session.id, machine=session.machine.name, reason=reason)


def allocate(
    db: Session,
    user: User,
    software_id: int | None,
    settings: Settings,
    waker: Waker,
    now: datetime,
    ip: str = "",
) -> RemoteSession:
    software: Software | None = None
    if software_id is not None:
        software = db.get(Software, software_id)
        if software is None:
            raise AllocationError("not_found", "프로그램을 찾을 수 없습니다", 404)

    for _ in range(3):  # 동시에 같은 PC 를 잡으려는 경쟁이 나면 다시 시도
        if open_session_for(db, user.id):
            raise AllocationError("already_open", "이미 사용 중인 PC 가 있습니다")

        if software is not None and software.license_limit is not None:
            if license_in_use(db, software.id) >= software.license_limit:
                raise AllocationError(
                    "license_full",
                    f"{software.name} 동시 사용 라이선스({software.license_limit}개)가 모두 사용 중입니다",
                )

        candidates = candidate_machines(db, settings, software, now)
        if not candidates:
            raise AllocationError("no_machine", "지금 사용할 수 있는 PC 가 없습니다. 잠시 후 다시 시도하세요")

        machine = candidates[0]
        session = RemoteSession(
            user=user,
            machine=machine,
            software=software,
            status=READY if machine.online else WAKING,
            created_at=now,
        )
        if machine.online:
            mark_ready(session, settings, now)
        db.add(session)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            continue

        audit(db, "session_start", user, ip=ip, session_id=session.id, machine=machine.name,
              software=software.name if software else None, status=session.status)
        db.commit()

        if session.status == WAKING:
            send_wake(db, session, waker, now)
            db.commit()
        return session

    raise AllocationError("conflict", "요청이 몰려 배정에 실패했습니다. 다시 시도하세요", 503)


def tick(db: Session, settings: Settings, prober, waker: Waker, now: datetime) -> None:
    """스케줄러 1회 실행: PC 상태 갱신 -> 켜지는 중인 세션 진행 -> 만료 처리."""
    machines = list(db.scalars(select(Machine).where(Machine.enabled.is_(True))))
    results = prober.probe(machines)
    for m in machines:
        online = results.get(m.id, False)
        m.online = online
        m.last_probe_at = now
        if online:
            m.last_seen_at = now

    sessions = list(db.scalars(select(RemoteSession).where(RemoteSession.status.in_(OPEN_STATUSES))))
    boot_timeout = timedelta(seconds=settings.boot_timeout_seconds)
    retry_after = timedelta(seconds=settings.wake_retry_after_seconds)
    no_show = timedelta(minutes=settings.no_show_minutes)

    for s in sessions:
        m = s.machine
        if s.status == WAKING:
            if m.online:
                mark_ready(s, settings, now)
                audit(db, "session_ready", s.user, session_id=s.id, machine=m.name,
                      boot_seconds=int((now - s.created_at).total_seconds()))
            elif now - s.created_at >= boot_timeout:
                m.wake_failures += 1
                m.last_wake_failure_at = now
                end_session(db, s, "boot_timeout", now, status=FAILED)
            elif (s.wake_sent_at is None or now - s.wake_sent_at >= retry_after) \
                    and s.wake_attempts < settings.wake_max_attempts:
                send_wake(db, s, waker, now)
        elif s.status == READY:
            if s.connected_at is None and s.ready_at and now - s.ready_at >= no_show:
                end_session(db, s, "no_show", now)
            elif s.expires_at and now >= s.expires_at:
                end_session(db, s, "expired", now)

    db.commit()
