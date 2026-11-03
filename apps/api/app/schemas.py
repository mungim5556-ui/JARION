from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- 인증
class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class UserOut(ORM):
    id: int
    username: str
    display_name: str
    role: str


# ---------- 학생용
class SoftwareAvailability(BaseModel):
    id: int
    name: str
    total: int          # 이 프로그램이 설치된 사용 가능 PC 수
    available_now: int  # 켜져 있고 비어 있음 (바로 접속)
    wakeable: int       # 꺼져 있고 비어 있음 (켜는 데 1~3분)
    in_use: int
    license_limit: int | None
    license_in_use: int


class LabSummary(BaseModel):
    id: int
    name: str
    location: str
    total: int
    online: int
    in_use: int


class CatalogOut(BaseModel):
    software: list[SoftwareAvailability]
    labs: list[LabSummary]


class SessionCreate(BaseModel):
    software_id: int | None = None


class SessionOut(BaseModel):
    id: int
    status: str
    end_reason: str | None
    machine_name: str
    lab_name: str
    software_name: str | None
    created_at: datetime
    ready_at: datetime | None
    connected_at: datetime | None
    expires_at: datetime | None
    ended_at: datetime | None
    boot_timeout_seconds: int


class CurrentSessionOut(BaseModel):
    session: SessionOut | None
    last: SessionOut | None  # 최근 끝난/실패한 세션 (안내 메시지용)


class ConnectOut(BaseModel):
    data: str            # Guacamole encrypted JSON
    guacamole_base: str  # 예: /guacamole
    expires_at: datetime


# ---------- 관리자
class LabIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    location: str = ""
    broadcast_address: str = "255.255.255.255"
    wol_relay_url: str = ""


class LabPatch(BaseModel):
    name: str | None = None
    location: str | None = None
    broadcast_address: str | None = None
    wol_relay_url: str | None = None


class LabOut(ORM):
    id: int
    name: str
    location: str
    broadcast_address: str
    wol_relay_url: str


class SoftwareIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    license_limit: int | None = Field(default=None, ge=0)


class SoftwarePatch(BaseModel):
    name: str | None = None
    license_limit: int | None = Field(default=None, ge=0)
    clear_license_limit: bool = False


class SoftwareOut(ORM):
    id: int
    name: str
    license_limit: int | None


MAC_PATTERN = r"^[0-9A-Fa-f]{2}([:\-][0-9A-Fa-f]{2}){5}$"


class MachineIn(BaseModel):
    lab_id: int
    name: str = Field(min_length=1, max_length=100)
    hostname: str = Field(min_length=1, max_length=200)
    mac: str = Field(pattern=MAC_PATTERN)
    rdp_port: int = Field(default=3389, ge=1, le=65535)
    gpu: str = ""
    notes: str = ""
    enabled: bool = True
    software_ids: list[int] = []


class MachinePatch(BaseModel):
    lab_id: int | None = None
    name: str | None = None
    hostname: str | None = None
    mac: str | None = Field(default=None, pattern=MAC_PATTERN)
    rdp_port: int | None = Field(default=None, ge=1, le=65535)
    gpu: str | None = None
    notes: str | None = None
    enabled: bool | None = None
    software_ids: list[int] | None = None


class MachineOut(BaseModel):
    id: int
    lab_id: int
    lab_name: str
    name: str
    hostname: str
    mac: str
    rdp_port: int
    gpu: str
    notes: str
    enabled: bool
    online: bool
    last_seen_at: datetime | None
    last_used_at: datetime | None
    wake_failures: int
    last_wake_failure_at: datetime | None
    software: list[SoftwareOut]
    session_id: int | None
    session_status: str | None
    session_user: str | None


class MachineImportIn(BaseModel):
    lab_id: int
    csv: str  # scripts/windows/Setup-LabPC.ps1 이 만든 CSV 내용


class MachineImportOut(BaseModel):
    created: list[str]
    updated: list[str]
    skipped: list[str]


class AdminSessionOut(SessionOut):
    username: str
    display_name: str
    machine_id: int


class UserIn(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    display_name: str = ""
    password: str = Field(min_length=8, max_length=200)
    role: str = Field(default="student", pattern="^(student|admin)$")


class UserPatch(BaseModel):
    display_name: str | None = None
    password: str | None = Field(default=None, min_length=8, max_length=200)
    role: str | None = Field(default=None, pattern="^(student|admin)$")
    is_active: bool | None = None


class AdminUserOut(UserOut):
    is_active: bool
    created_at: datetime


class AuditOut(ORM):
    id: int
    at: datetime
    username: str
    action: str
    detail: str
    ip: str
