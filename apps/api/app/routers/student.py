from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..allocator import (
    AllocationError,
    allocate,
    busy_machine_ids,
    end_session,
    license_in_use,
    open_session_for,
)
from ..audit import audit
from ..config import Settings
from ..db import utcnow
from ..deps import get_db, get_settings_dep, get_waker
from ..guacamole import build_connect_data
from ..models import READY, Lab, Machine, RemoteSession, Software, User
from ..schemas import (
    CatalogOut,
    ConnectOut,
    CurrentSessionOut,
    LabSummary,
    SessionCreate,
    SessionOut,
    SoftwareAvailability,
)
from ..security import client_ip, current_user
from ..views import session_out

router = APIRouter(prefix="/api", tags=["student"])


@router.get("/catalog", response_model=CatalogOut)
def catalog(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    _: User = Depends(current_user),
):
    now = utcnow()
    cooldown_since = now - timedelta(minutes=settings.wake_failure_cooldown_minutes)
    machines = list(db.scalars(select(Machine).where(Machine.enabled.is_(True))))
    busy = busy_machine_ids(db)

    def usable(m: Machine) -> bool:
        return m.last_wake_failure_at is None or m.last_wake_failure_at < cooldown_since

    software_out = []
    for sw in db.scalars(select(Software).order_by(Software.name)):
        ms = [m for m in machines if any(x.id == sw.id for x in m.software)]
        free = [m for m in ms if m.id not in busy and usable(m)]
        software_out.append(
            SoftwareAvailability(
                id=sw.id,
                name=sw.name,
                total=len(ms),
                available_now=sum(1 for m in free if m.online),
                wakeable=sum(1 for m in free if not m.online and m.lab.wol_relay_url),
                in_use=sum(1 for m in ms if m.id in busy),
                license_limit=sw.license_limit,
                license_in_use=license_in_use(db, sw.id),
            )
        )

    labs_out = []
    for lab in db.scalars(select(Lab).order_by(Lab.name)):
        ms = [m for m in machines if m.lab_id == lab.id]
        labs_out.append(
            LabSummary(
                id=lab.id,
                name=lab.name,
                location=lab.location,
                total=len(ms),
                online=sum(1 for m in ms if m.online),
                in_use=sum(1 for m in ms if m.id in busy),
            )
        )
    return CatalogOut(software=software_out, labs=labs_out)


@router.get("/sessions/current", response_model=CurrentSessionOut)
def current_session(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    user: User = Depends(current_user),
):
    s = open_session_for(db, user.id)
    last = None
    if s is None:
        recent = db.scalar(
            select(RemoteSession)
            .where(RemoteSession.user_id == user.id, RemoteSession.ended_at >= utcnow() - timedelta(minutes=10))
            .order_by(RemoteSession.ended_at.desc())
            .limit(1)
        )
        last = session_out(recent, settings) if recent else None
    return CurrentSessionOut(session=session_out(s, settings) if s else None, last=last)


@router.post("/sessions", response_model=SessionOut, status_code=201)
def create_session(
    body: SessionCreate,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    waker=Depends(get_waker),
    user: User = Depends(current_user),
):
    try:
        s = allocate(db, user, body.software_id, settings, waker, utcnow(), ip=client_ip(request))
    except AllocationError as e:
        raise HTTPException(e.status_code, {"code": e.code, "message": e.message}) from None
    return session_out(s, settings)


def _own_session(db: Session, session_id: int, user: User) -> RemoteSession:
    s = db.get(RemoteSession, session_id)
    if s is None or s.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "세션을 찾을 수 없습니다")
    return s


@router.post("/sessions/{session_id}/connect", response_model=ConnectOut)
def connect(
    session_id: int,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    user: User = Depends(current_user),
):
    s = _own_session(db, session_id, user)
    if s.status != READY:
        raise HTTPException(status.HTTP_409_CONFLICT, "아직 접속할 수 없는 상태입니다")
    now = utcnow()
    data, expires = build_connect_data(settings, s, now)
    if s.connected_at is None:
        s.connected_at = now
    audit(db, "connect", user, ip=client_ip(request), session_id=s.id, machine=s.machine.name)
    db.commit()
    return ConnectOut(data=data, guacamole_base=settings.guac_base_path, expires_at=expires)


@router.post("/sessions/{session_id}/end", response_model=SessionOut)
def end(
    session_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    user: User = Depends(current_user),
):
    s = _own_session(db, session_id, user)
    if not s.is_open:
        raise HTTPException(status.HTTP_409_CONFLICT, "이미 종료된 세션입니다")
    end_session(db, s, "user", utcnow())
    db.commit()
    return session_out(s, settings)
