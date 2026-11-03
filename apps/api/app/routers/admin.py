import csv
import io
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..allocator import end_session, send_wake
from ..audit import audit
from ..config import Settings
from ..db import utcnow
from ..deps import get_db, get_settings_dep, get_waker
from ..models import OPEN_STATUSES, AuditLog, Lab, Machine, RemoteSession, Software, User
from ..power import WakeError
from ..schemas import (
    AdminSessionOut,
    AdminUserOut,
    AuditOut,
    LabIn,
    LabOut,
    LabPatch,
    MachineImportIn,
    MachineImportOut,
    MachineIn,
    MachineOut,
    MachinePatch,
    SoftwareIn,
    SoftwareOut,
    SoftwarePatch,
    UserIn,
    UserPatch,
)
from ..security import client_ip, hash_password, require_admin
from ..views import admin_session_out, machine_out

router = APIRouter(prefix="/api/admin", tags=["admin"])

MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}([:\-]?[0-9A-Fa-f]{2}){5}$")


def norm_mac(mac: str) -> str:
    hexes = re.sub(r"[^0-9A-Fa-f]", "", mac).upper()
    return ":".join(hexes[i:i + 2] for i in range(0, 12, 2))


def _commit(db: Session, what: str) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, f"{what} 이름이 중복됩니다") from None


def _get(db: Session, model, obj_id: int):
    obj = db.get(model, obj_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "찾을 수 없습니다")
    return obj


def _software(db: Session, ids: list[int]) -> list[Software]:
    found = list(db.scalars(select(Software).where(Software.id.in_(ids)))) if ids else []
    if len(found) != len(set(ids)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "존재하지 않는 프로그램이 있습니다")
    return found


def _open_sessions_by_machine(db: Session) -> dict[int, RemoteSession]:
    return {
        s.machine_id: s
        for s in db.scalars(select(RemoteSession).where(RemoteSession.status.in_(OPEN_STATUSES)))
    }


# ------------------------------------------------------------------ 실습실
@router.get("/labs", response_model=list[LabOut])
def list_labs(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return list(db.scalars(select(Lab).order_by(Lab.name)))


@router.post("/labs", response_model=LabOut, status_code=201)
def create_lab(body: LabIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    lab = Lab(**body.model_dump())
    db.add(lab)
    audit(db, "admin_lab_create", admin, name=body.name)
    _commit(db, "실습실")
    return lab


@router.patch("/labs/{lab_id}", response_model=LabOut)
def update_lab(lab_id: int, body: LabPatch, db: Session = Depends(get_db),
               admin: User = Depends(require_admin)):
    lab = _get(db, Lab, lab_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(lab, k, v)
    audit(db, "admin_lab_update", admin, lab=lab.name)
    _commit(db, "실습실")
    return lab


# ------------------------------------------------------------------ 프로그램
@router.get("/software", response_model=list[SoftwareOut])
def list_software(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return list(db.scalars(select(Software).order_by(Software.name)))


@router.post("/software", response_model=SoftwareOut, status_code=201)
def create_software(body: SoftwareIn, db: Session = Depends(get_db),
                    admin: User = Depends(require_admin)):
    sw = Software(**body.model_dump())
    db.add(sw)
    audit(db, "admin_software_create", admin, name=body.name, license_limit=body.license_limit)
    _commit(db, "프로그램")
    return sw


@router.patch("/software/{software_id}", response_model=SoftwareOut)
def update_software(software_id: int, body: SoftwarePatch, db: Session = Depends(get_db),
                    admin: User = Depends(require_admin)):
    sw = _get(db, Software, software_id)
    if body.name is not None:
        sw.name = body.name
    if body.clear_license_limit:
        sw.license_limit = None
    elif body.license_limit is not None:
        sw.license_limit = body.license_limit
    audit(db, "admin_software_update", admin, name=sw.name, license_limit=sw.license_limit)
    _commit(db, "프로그램")
    return sw


# ------------------------------------------------------------------ PC
@router.get("/machines", response_model=list[MachineOut])
def list_machines(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    open_by_machine = _open_sessions_by_machine(db)
    machines = db.scalars(select(Machine).join(Lab).order_by(Lab.name, Machine.name))
    return [machine_out(m, open_by_machine.get(m.id)) for m in machines]


@router.post("/machines", response_model=MachineOut, status_code=201)
def create_machine(body: MachineIn, db: Session = Depends(get_db),
                   admin: User = Depends(require_admin)):
    _get(db, Lab, body.lab_id)
    data = body.model_dump(exclude={"software_ids"})
    data["mac"] = norm_mac(data["mac"])
    m = Machine(**data, software=_software(db, body.software_ids))
    db.add(m)
    audit(db, "admin_machine_create", admin, name=m.name)
    _commit(db, "PC")
    return machine_out(m, None)


@router.patch("/machines/{machine_id}", response_model=MachineOut)
def update_machine(machine_id: int, body: MachinePatch, db: Session = Depends(get_db),
                   admin: User = Depends(require_admin)):
    m = _get(db, Machine, machine_id)
    changes = body.model_dump(exclude_unset=True)
    if "software_ids" in changes:
        ids = changes.pop("software_ids")
        if ids is not None:
            m.software = _software(db, ids)
    if changes.get("lab_id") is not None:
        _get(db, Lab, changes["lab_id"])
    if changes.get("mac"):
        changes["mac"] = norm_mac(changes["mac"])
    for k, v in changes.items():
        if v is not None:
            setattr(m, k, v)
    audit(db, "admin_machine_update", admin, name=m.name, changes=body.model_dump(exclude_unset=True))
    _commit(db, "PC")
    return machine_out(m, _open_sessions_by_machine(db).get(m.id))


@router.delete("/machines/{machine_id}", status_code=204)
def delete_machine(machine_id: int, db: Session = Depends(get_db),
                   admin: User = Depends(require_admin)):
    m = _get(db, Machine, machine_id)
    has_sessions = db.scalar(select(RemoteSession.id).where(RemoteSession.machine_id == m.id).limit(1))
    if has_sessions:
        raise HTTPException(status.HTTP_409_CONFLICT, "사용 기록이 있는 PC 는 삭제 대신 '사용 안 함'으로 바꾸세요")
    audit(db, "admin_machine_delete", admin, name=m.name)
    db.delete(m)
    db.commit()


@router.post("/machines/{machine_id}/wake", status_code=202)
def wake_machine(machine_id: int, request: Request, db: Session = Depends(get_db),
                 waker=Depends(get_waker), admin: User = Depends(require_admin)):
    m = _get(db, Machine, machine_id)
    try:
        waker.wake(m)
    except WakeError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from None
    finally:
        audit(db, "admin_machine_wake", admin, ip=client_ip(request), name=m.name)
        db.commit()
    return {"ok": True}


@router.post("/machines/import", response_model=MachineImportOut)
def import_machines(body: MachineImportIn, db: Session = Depends(get_db),
                    admin: User = Depends(require_admin)):
    """Setup-LabPC.ps1 이 만든 CSV(ComputerName,MAC,IPv4,NIC,GPU,Software,...)로 PC 를 등록/갱신."""
    _get(db, Lab, body.lab_id)
    all_sw = list(db.scalars(select(Software)))
    text = body.csv.lstrip("﻿")
    reader = csv.DictReader(io.StringIO(text))
    created, updated, skipped, seen = [], [], [], set()

    for row in reader:
        name = (row.get("ComputerName") or "").strip()
        mac = (row.get("MAC") or "").strip()
        ip = (row.get("IPv4") or "").strip()
        if not name or name in seen:
            continue
        if not MAC_RE.match(mac) or not ip:
            skipped.append(f"{name or '?'}: MAC/IP 없음")
            continue
        seen.add(name)
        installed = (row.get("Software") or "").lower()
        matched = [sw for sw in all_sw if sw.name.lower() in installed]

        m = db.scalar(select(Machine).where(Machine.name == name))
        if m is None:
            m = Machine(lab_id=body.lab_id, name=name, hostname=ip, mac=norm_mac(mac),
                        gpu=(row.get("GPU") or "").strip(), software=matched)
            db.add(m)
            created.append(name)
        else:
            m.lab_id = body.lab_id
            m.hostname = ip
            m.mac = norm_mac(mac)
            m.gpu = (row.get("GPU") or "").strip() or m.gpu
            if matched:
                m.software = sorted({*m.software, *matched}, key=lambda s: s.id)
            updated.append(name)

    audit(db, "admin_machine_import", admin, created=len(created), updated=len(updated))
    _commit(db, "PC")
    return MachineImportOut(created=created, updated=updated, skipped=skipped)


# ------------------------------------------------------------------ 세션
@router.get("/sessions", response_model=list[AdminSessionOut])
def list_sessions(
    open_only: bool = Query(default=True),
    limit: int = Query(default=100, le=1000),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    _: User = Depends(require_admin),
):
    q = select(RemoteSession).order_by(RemoteSession.created_at.desc()).limit(limit)
    if open_only:
        q = q.where(RemoteSession.status.in_(OPEN_STATUSES))
    return [admin_session_out(s, settings) for s in db.scalars(q)]


@router.post("/sessions/{session_id}/end", response_model=AdminSessionOut)
def force_end(session_id: int, db: Session = Depends(get_db),
              settings: Settings = Depends(get_settings_dep), admin: User = Depends(require_admin)):
    s = _get(db, RemoteSession, session_id)
    if not s.is_open:
        raise HTTPException(status.HTTP_409_CONFLICT, "이미 종료된 세션입니다")
    end_session(db, s, "admin", utcnow(), actor=admin)
    db.commit()
    return admin_session_out(s, settings)


@router.post("/sessions/{session_id}/rewake", status_code=202)
def rewake(session_id: int, db: Session = Depends(get_db), waker=Depends(get_waker),
           _: User = Depends(require_admin)):
    s = _get(db, RemoteSession, session_id)
    if s.status != "waking":
        raise HTTPException(status.HTTP_409_CONFLICT, "켜는 중인 세션이 아닙니다")
    send_wake(db, s, waker, utcnow())
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ 사용자
@router.get("/users", response_model=list[AdminUserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return list(db.scalars(select(User).order_by(User.username)))


@router.post("/users", response_model=AdminUserOut, status_code=201)
def create_user(body: UserIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    u = User(username=body.username, display_name=body.display_name, role=body.role,
             password_hash=hash_password(body.password))
    db.add(u)
    audit(db, "admin_user_create", admin, username=body.username, role=body.role)
    _commit(db, "사용자")
    return u


@router.patch("/users/{user_id}", response_model=AdminUserOut)
def update_user(user_id: int, body: UserPatch, db: Session = Depends(get_db),
                admin: User = Depends(require_admin)):
    u = _get(db, User, user_id)
    if u.id == admin.id and (body.role == "student" or body.is_active is False):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "자기 자신의 관리자 권한은 해제할 수 없습니다")
    if body.display_name is not None:
        u.display_name = body.display_name
    if body.password is not None:
        u.password_hash = hash_password(body.password)
    if body.role is not None:
        u.role = body.role
    if body.is_active is not None:
        u.is_active = body.is_active
    audit(db, "admin_user_update", admin, username=u.username,
          changes=body.model_dump(exclude_unset=True, exclude={"password"}))
    db.commit()
    return u


# ------------------------------------------------------------------ 감사 로그
@router.get("/audit", response_model=list[AuditOut])
def list_audit(
    limit: int = Query(default=200, le=2000),
    action: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    q = select(AuditLog).order_by(AuditLog.at.desc(), AuditLog.id.desc()).limit(limit)
    if action:
        q = q.where(AuditLog.action == action)
    return list(db.scalars(q))
