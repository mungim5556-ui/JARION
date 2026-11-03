export type User = { id: number; username: string; display_name: string; role: "student" | "admin" };

export type SoftwareAvailability = {
  id: number;
  name: string;
  total: number;
  available_now: number;
  wakeable: number;
  in_use: number;
  license_limit: number | null;
  license_in_use: number;
};

export type LabSummary = { id: number; name: string; location: string; total: number; online: number; in_use: number };

export type SessionStatus = "waking" | "ready" | "ended" | "failed";

export type RemoteSession = {
  id: number;
  status: SessionStatus;
  end_reason: string | null;
  machine_name: string;
  lab_name: string;
  software_name: string | null;
  created_at: string;
  ready_at: string | null;
  connected_at: string | null;
  expires_at: string | null;
  ended_at: string | null;
  boot_timeout_seconds: number;
};

export type AdminSession = RemoteSession & { username: string; display_name: string; machine_id: number };

export type Software = { id: number; name: string; license_limit: number | null };
export type Lab = { id: number; name: string; location: string; broadcast_address: string; wol_relay_url: string };

export type Machine = {
  id: number;
  lab_id: number;
  lab_name: string;
  name: string;
  hostname: string;
  mac: string;
  rdp_port: number;
  gpu: string;
  notes: string;
  enabled: boolean;
  online: boolean;
  last_seen_at: string | null;
  last_used_at: string | null;
  wake_failures: number;
  last_wake_failure_at: string | null;
  software: Software[];
  session_id: number | null;
  session_status: SessionStatus | null;
  session_user: string | null;
  agent_status: "none" | "ok" | "stale";
  agent_version: string;
  agent_seen_at: string | null;
  console_user: string;
  remote_users: string;
  remote_state: "none" | "active" | "disconnected";
  running: string;
};

export type AdminUser = User & { is_active: boolean; created_at: string };
export type Audit = { id: number; at: string; username: string; action: string; detail: string; ip: string };

export class ApiError extends Error {
  constructor(public status: number, message: string, public code?: string) {
    super(message);
  }
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init;
  const res = await fetch(path, {
    credentials: "same-origin",
    ...rest,
    headers: { ...(json !== undefined ? { "Content-Type": "application/json" } : {}), ...headers },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = body?.detail;
    if (detail && typeof detail === "object" && !Array.isArray(detail)) {
      throw new ApiError(res.status, detail.message ?? "오류가 발생했습니다", detail.code);
    }
    if (Array.isArray(detail)) {
      throw new ApiError(res.status, "입력값을 확인하세요: " + detail.map((d: { msg: string }) => d.msg).join(", "));
    }
    throw new ApiError(res.status, typeof detail === "string" ? detail : `요청 실패 (${res.status})`);
  }
  return body as T;
}

/**
 * 원격 접속: 포털에서 받은 1회용 데이터로 Guacamole 토큰을 받고 새 탭에서 연다.
 * 팝업 차단을 피하려고 클릭 직후 빈 탭을 먼저 연다.
 */
export async function openRemote(sessionId: number): Promise<void> {
  const tab = window.open("about:blank", "_blank");
  try {
    const { data, guacamole_base } = await api<{ data: string; guacamole_base: string }>(
      `/api/sessions/${sessionId}/connect`,
      { method: "POST" },
    );
    const res = await fetch(`${guacamole_base}/api/tokens`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ data }),
    });
    if (!res.ok) throw new ApiError(res.status, "원격 접속 서버 인증에 실패했습니다");
    const { authToken } = (await res.json()) as { authToken: string };
    const url = `${guacamole_base}/#/?token=${encodeURIComponent(authToken)}`;
    if (tab) tab.location.href = url;
    else window.location.href = url;
  } catch (e) {
    tab?.close();
    throw e;
  }
}

export function fmtTime(iso: string | null): string {
  if (!iso) return "-";
  return new Date(iso).toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function fmtRemaining(ms: number): string {
  if (ms <= 0) return "0분";
  const m = Math.floor(ms / 60000);
  const h = Math.floor(m / 60);
  return h > 0 ? `${h}시간 ${m % 60}분` : `${m}분`;
}

export const END_REASON: Record<string, string> = {
  user: "직접 반납",
  admin: "관리자가 종료",
  expired: "사용 시간 만료",
  no_show: "접속하지 않아 자동 반납",
  boot_timeout: "PC 가 켜지지 않음",
  logged_off: "원격 PC 에서 직접 로그오프",
  disconnected: "연결이 끊긴 채 오래 방치",
};
