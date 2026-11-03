"""ORM -> 응답 스키마 변환."""
from .config import Settings
from .models import Machine, RemoteSession
from .schemas import AdminSessionOut, MachineOut, SessionOut, SoftwareOut


def session_out(s: RemoteSession, settings: Settings) -> SessionOut:
    return SessionOut(
        id=s.id,
        status=s.status,
        end_reason=s.end_reason,
        machine_name=s.machine.name,
        lab_name=s.machine.lab.name,
        software_name=s.software.name if s.software else None,
        created_at=s.created_at,
        ready_at=s.ready_at,
        connected_at=s.connected_at,
        expires_at=s.expires_at,
        ended_at=s.ended_at,
        boot_timeout_seconds=settings.boot_timeout_seconds,
    )


def admin_session_out(s: RemoteSession, settings: Settings) -> AdminSessionOut:
    return AdminSessionOut(
        **session_out(s, settings).model_dump(),
        username=s.user.username,
        display_name=s.user.display_name,
        machine_id=s.machine_id,
    )


def machine_out(m: Machine, open_session: RemoteSession | None) -> MachineOut:
    return MachineOut(
        id=m.id,
        lab_id=m.lab_id,
        lab_name=m.lab.name,
        name=m.name,
        hostname=m.hostname,
        mac=m.mac,
        rdp_port=m.rdp_port,
        gpu=m.gpu,
        notes=m.notes,
        enabled=m.enabled,
        online=m.online,
        last_seen_at=m.last_seen_at,
        last_used_at=m.last_used_at,
        wake_failures=m.wake_failures,
        last_wake_failure_at=m.last_wake_failure_at,
        software=[SoftwareOut.model_validate(sw) for sw in sorted(m.software, key=lambda x: x.name)],
        session_id=open_session.id if open_session else None,
        session_status=open_session.status if open_session else None,
        session_user=open_session.user.username if open_session else None,
    )
