"use client";

import { useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import {
  api,
  ApiError,
  END_REASON,
  fmtTime,
  type AdminSession,
  type AdminUser,
  type Audit,
  type Lab,
  type Machine,
  type Software,
} from "@/lib/api";

const TABS = ["PC", "세션", "실습실·프로그램", "사용자", "로그"] as const;
type Tab = (typeof TABS)[number];

export default function AdminPage() {
  const [tab, setTab] = useState<Tab>("PC");
  return (
    <Shell adminOnly>
      <h1>관리</h1>
      <p className="sub">PC 상태는 10초마다 갱신됩니다.</p>
      <div className="tabs">
        {TABS.map((t) => (
          <button key={t} className={`tab ${t === tab ? "active" : ""}`} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </div>
      {tab === "PC" && <MachinesTab />}
      {tab === "세션" && <SessionsTab />}
      {tab === "실습실·프로그램" && <SetupTab />}
      {tab === "사용자" && <UsersTab />}
      {tab === "로그" && <AuditTab />}
    </Shell>
  );
}

/** 공통: 불러오기 + 주기 갱신 + 오류 표시 */
function useLoad<T>(path: string, intervalMs = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const reload = useCallback(async () => {
    try {
      setData(await api<T>(path));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "불러오기 실패");
    }
  }, [path]);
  useEffect(() => {
    reload();
    if (!intervalMs) return;
    const t = setInterval(reload, intervalMs);
    return () => clearInterval(t);
  }, [reload, intervalMs]);
  return { data, error, setError, reload };
}

async function act(fn: () => Promise<unknown>, setError: (s: string) => void, after: () => void) {
  setError("");
  try {
    await fn();
  } catch (e) {
    setError(e instanceof ApiError ? e.message : "요청 실패");
  } finally {
    after();
  }
}

function machineBadge(m: Machine) {
  if (!m.enabled) return <span className="badge">사용 안 함</span>;
  if (m.session_status === "waking") return <span className="badge warn"><span className="dot" />켜는 중</span>;
  if (m.session_status === "ready") return <span className="badge warn"><span className="dot" />사용 중</span>;
  if (m.online) return <span className="badge ok"><span className="dot" />켜짐 · 비어 있음</span>;
  return <span className="badge"><span className="dot" />꺼짐</span>;
}

// ------------------------------------------------------------------ PC
function MachinesTab() {
  const { data, error, setError, reload } = useLoad<Machine[]>("/api/admin/machines", 10000);
  const software = useLoad<Software[]>("/api/admin/software");
  const [editing, setEditing] = useState<number | null>(null);

  if (!data) return <p className="muted">불러오는 중…</p>;
  return (
    <div className="stack">
      {error && <div className="alert error">{error}</div>}
      <div className="card table-wrap">
        <table>
          <thead>
            <tr>
              <th>상태</th>
              <th>PC</th>
              <th>실습실</th>
              <th>IP / MAC</th>
              <th>프로그램</th>
              <th>사용자</th>
              <th>마지막 응답</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data.length === 0 && (
              <tr>
                <td colSpan={8} className="muted">
                  등록된 PC 가 없습니다. 아래에서 CSV 로 가져오세요.
                </td>
              </tr>
            )}
            {data.map((m) => (
              <tr key={m.id}>
                <td>
                  {machineBadge(m)}
                  {m.wake_failures > 0 && <div className="small" style={{ color: "var(--danger)" }}>켜기 실패 {m.wake_failures}회</div>}
                </td>
                <td>
                  <b>{m.name}</b>
                  {m.gpu && <div className="muted small">{m.gpu}</div>}
                </td>
                <td>{m.lab_name}</td>
                <td className="mono">
                  {m.hostname}
                  <br />
                  {m.mac}
                </td>
                <td>
                  {editing === m.id && software.data ? (
                    <SoftwarePicker
                      all={software.data}
                      selected={m.software.map((s) => s.id)}
                      onSave={(ids) =>
                        act(
                          () => api(`/api/admin/machines/${m.id}`, { method: "PATCH", json: { software_ids: ids } }),
                          setError,
                          () => {
                            setEditing(null);
                            reload();
                          },
                        )
                      }
                      onCancel={() => setEditing(null)}
                    />
                  ) : (
                    <span>
                      {m.software.map((s) => s.name).join(", ") || <span className="muted">없음</span>}{" "}
                      <button className="btn sm" onClick={() => setEditing(m.id)}>
                        변경
                      </button>
                    </span>
                  )}
                </td>
                <td>{m.session_user ?? "-"}</td>
                <td className="small">{fmtTime(m.last_seen_at)}</td>
                <td>
                  <div className="row">
                    <button
                      className="btn sm"
                      disabled={m.online}
                      onClick={() => act(() => api(`/api/admin/machines/${m.id}/wake`, { method: "POST" }), setError, reload)}
                    >
                      켜기
                    </button>
                    <button
                      className="btn sm"
                      onClick={() =>
                        act(
                          () => api(`/api/admin/machines/${m.id}`, { method: "PATCH", json: { enabled: !m.enabled } }),
                          setError,
                          reload,
                        )
                      }
                    >
                      {m.enabled ? "사용 안 함" : "사용"}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ImportCard onDone={reload} />
    </div>
  );
}

function SoftwarePicker({
  all,
  selected,
  onSave,
  onCancel,
}: {
  all: Software[];
  selected: number[];
  onSave: (ids: number[]) => void;
  onCancel: () => void;
}) {
  const [ids, setIds] = useState(selected);
  return (
    <div className="stack" style={{ gap: 6 }}>
      {all.map((s) => (
        <label key={s.id} className="row" style={{ color: "var(--text)", margin: 0 }}>
          <input
            type="checkbox"
            style={{ width: "auto" }}
            checked={ids.includes(s.id)}
            onChange={(e) => setIds(e.target.checked ? [...ids, s.id] : ids.filter((x) => x !== s.id))}
          />
          {s.name}
        </label>
      ))}
      <div className="row">
        <button className="btn sm primary" onClick={() => onSave(ids)}>
          저장
        </button>
        <button className="btn sm" onClick={onCancel}>
          취소
        </button>
      </div>
    </div>
  );
}

function ImportCard({ onDone }: { onDone: () => void }) {
  const labs = useLoad<Lab[]>("/api/admin/labs");
  const [labId, setLabId] = useState<number | "">("");
  const [csv, setCsv] = useState("");
  const [result, setResult] = useState("");
  const [error, setError] = useState("");

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (f) setCsv(await f.text());
  }

  async function submit() {
    setResult("");
    await act(
      async () => {
        const r = await api<{ created: string[]; updated: string[]; skipped: string[] }>("/api/admin/machines/import", {
          method: "POST",
          json: { lab_id: labId, csv },
        });
        setResult(
          `추가 ${r.created.length}대, 갱신 ${r.updated.length}대` +
            (r.skipped.length ? `, 건너뜀: ${r.skipped.join(" / ")}` : ""),
        );
        setCsv("");
      },
      setError,
      onDone,
    );
  }

  return (
    <div className="card">
      <h2>PC 가져오기 (CSV)</h2>
      <p className="muted small" style={{ marginTop: 0 }}>
        각 PC 에서 <code>Setup-LabPC.ps1</code> 을 실행해 만든 CSV 를 올리세요. 같은 이름의 PC 는 IP/MAC 이 갱신되고, 설치된
        프로그램은 등록된 프로그램 이름과 비교해 자동으로 연결됩니다.
      </p>
      {error && <div className="alert error" style={{ marginBottom: 12 }}>{error}</div>}
      {result && <div className="alert info" style={{ marginBottom: 12 }}>{result}</div>}
      <div className="field">
        <label>실습실</label>
        <select value={labId} onChange={(e) => setLabId(e.target.value ? Number(e.target.value) : "")}>
          <option value="">선택</option>
          {labs.data?.map((l) => (
            <option key={l.id} value={l.id}>
              {l.name}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label>CSV 파일</label>
        <input type="file" accept=".csv,text/csv" onChange={onFile} />
      </div>
      <div className="field">
        <textarea rows={4} value={csv} onChange={(e) => setCsv(e.target.value)} placeholder="또는 CSV 내용을 붙여 넣기" />
      </div>
      <button className="btn primary" disabled={!labId || !csv.trim()} onClick={submit}>
        가져오기
      </button>
    </div>
  );
}

// ------------------------------------------------------------------ 세션
function SessionsTab() {
  const [openOnly, setOpenOnly] = useState(true);
  const { data, error, setError, reload } = useLoad<AdminSession[]>(`/api/admin/sessions?open_only=${openOnly}`, 10000);

  return (
    <div className="stack">
      <div className="row">
        <label className="row" style={{ margin: 0, color: "var(--text)" }}>
          <input type="checkbox" style={{ width: "auto" }} checked={openOnly} onChange={(e) => setOpenOnly(e.target.checked)} />
          사용 중인 세션만
        </label>
      </div>
      {error && <div className="alert error">{error}</div>}
      <div className="card table-wrap">
        <table>
          <thead>
            <tr>
              <th>상태</th>
              <th>사용자</th>
              <th>PC</th>
              <th>프로그램</th>
              <th>시작</th>
              <th>접속</th>
              <th>종료(예정)</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data?.length === 0 && (
              <tr>
                <td colSpan={8} className="muted">
                  세션이 없습니다.
                </td>
              </tr>
            )}
            {data?.map((s) => (
              <tr key={s.id}>
                <td>
                  {s.status === "ready" && <span className="badge ok">사용 중</span>}
                  {s.status === "waking" && <span className="badge warn">켜는 중</span>}
                  {s.status === "ended" && <span className="badge">종료</span>}
                  {s.status === "failed" && <span className="badge danger">실패</span>}
                  {s.end_reason && <div className="muted small">{END_REASON[s.end_reason] ?? s.end_reason}</div>}
                </td>
                <td>
                  {s.display_name || s.username}
                  <div className="muted small">{s.username}</div>
                </td>
                <td>
                  {s.machine_name}
                  <div className="muted small">{s.lab_name}</div>
                </td>
                <td>{s.software_name ?? "-"}</td>
                <td className="small">{fmtTime(s.created_at)}</td>
                <td className="small">{fmtTime(s.connected_at)}</td>
                <td className="small">{fmtTime(s.ended_at ?? s.expires_at)}</td>
                <td>
                  {(s.status === "ready" || s.status === "waking") && (
                    <div className="row">
                      {s.status === "waking" && (
                        <button
                          className="btn sm"
                          onClick={() => act(() => api(`/api/admin/sessions/${s.id}/rewake`, { method: "POST" }), setError, reload)}
                        >
                          다시 켜기
                        </button>
                      )}
                      <button
                        className="btn sm danger"
                        onClick={() => {
                          if (confirm(`${s.username} 의 세션을 종료할까요?`))
                            act(() => api(`/api/admin/sessions/${s.id}/end`, { method: "POST" }), setError, reload);
                        }}
                      >
                        강제 종료
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ 실습실·프로그램
function SetupTab() {
  const labs = useLoad<Lab[]>("/api/admin/labs");
  const sw = useLoad<Software[]>("/api/admin/software");
  const [error, setError] = useState("");
  const [lab, setLab] = useState({ name: "", location: "", broadcast_address: "", wol_relay_url: "" });
  const [newSw, setNewSw] = useState({ name: "", license_limit: "" });

  return (
    <div className="stack">
      {error && <div className="alert error">{error}</div>}
      <div className="card">
        <h2>실습실</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>이름</th>
                <th>위치</th>
                <th>브로드캐스트 주소</th>
                <th>WoL 릴레이</th>
              </tr>
            </thead>
            <tbody>
              {labs.data?.map((l) => (
                <LabRow key={l.id} lab={l} onSaved={labs.reload} setError={setError} />
              ))}
            </tbody>
          </table>
        </div>
        <h2 style={{ marginTop: 20 }}>실습실 추가</h2>
        <div className="grid">
          <input placeholder="이름 (예: 공학관 301호)" value={lab.name} onChange={(e) => setLab({ ...lab, name: e.target.value })} />
          <input placeholder="위치" value={lab.location} onChange={(e) => setLab({ ...lab, location: e.target.value })} />
          <input
            placeholder="브로드캐스트 (예: 10.20.30.255)"
            value={lab.broadcast_address}
            onChange={(e) => setLab({ ...lab, broadcast_address: e.target.value })}
          />
          <input
            placeholder="릴레이 URL (예: http://10.20.30.5:8080)"
            value={lab.wol_relay_url}
            onChange={(e) => setLab({ ...lab, wol_relay_url: e.target.value })}
          />
        </div>
        <button
          className="btn primary"
          style={{ marginTop: 12 }}
          disabled={!lab.name}
          onClick={() =>
            act(
              () =>
                api("/api/admin/labs", {
                  method: "POST",
                  json: { ...lab, broadcast_address: lab.broadcast_address || "255.255.255.255" },
                }),
              setError,
              () => {
                setLab({ name: "", location: "", broadcast_address: "", wol_relay_url: "" });
                labs.reload();
              },
            )
          }
        >
          추가
        </button>
      </div>

      <div className="card">
        <h2>프로그램</h2>
        <p className="muted small" style={{ marginTop: 0 }}>
          동시 사용 라이선스 수를 넣으면 그 수 이상 동시에 배정하지 않습니다. 비워 두면 제한 없음.
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>이름</th>
                <th>동시 사용 라이선스</th>
              </tr>
            </thead>
            <tbody>
              {sw.data?.map((s) => (
                <SoftwareRow key={s.id} sw={s} onSaved={sw.reload} setError={setError} />
              ))}
            </tbody>
          </table>
        </div>
        <div className="row" style={{ marginTop: 12 }}>
          <input
            style={{ maxWidth: 240 }}
            placeholder="이름 (예: Revit)"
            value={newSw.name}
            onChange={(e) => setNewSw({ ...newSw, name: e.target.value })}
          />
          <input
            style={{ maxWidth: 160 }}
            type="number"
            min={0}
            placeholder="라이선스 수"
            value={newSw.license_limit}
            onChange={(e) => setNewSw({ ...newSw, license_limit: e.target.value })}
          />
          <button
            className="btn primary"
            disabled={!newSw.name}
            onClick={() =>
              act(
                () =>
                  api("/api/admin/software", {
                    method: "POST",
                    json: { name: newSw.name, license_limit: newSw.license_limit ? Number(newSw.license_limit) : null },
                  }),
                setError,
                () => {
                  setNewSw({ name: "", license_limit: "" });
                  sw.reload();
                },
              )
            }
          >
            추가
          </button>
        </div>
      </div>
    </div>
  );
}

function LabRow({ lab, onSaved, setError }: { lab: Lab; onSaved: () => void; setError: (s: string) => void }) {
  const [v, setV] = useState(lab);
  const dirty = JSON.stringify(v) !== JSON.stringify(lab);
  return (
    <tr>
      <td>
        <input value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} />
      </td>
      <td>
        <input value={v.location} onChange={(e) => setV({ ...v, location: e.target.value })} />
      </td>
      <td>
        <input className="mono" value={v.broadcast_address} onChange={(e) => setV({ ...v, broadcast_address: e.target.value })} />
      </td>
      <td>
        <div className="row" style={{ flexWrap: "nowrap" }}>
          <input className="mono" value={v.wol_relay_url} onChange={(e) => setV({ ...v, wol_relay_url: e.target.value })} />
          <button
            className="btn sm primary"
            disabled={!dirty}
            onClick={() => act(() => api(`/api/admin/labs/${lab.id}`, { method: "PATCH", json: v }), setError, onSaved)}
          >
            저장
          </button>
        </div>
      </td>
    </tr>
  );
}

function SoftwareRow({ sw, onSaved, setError }: { sw: Software; onSaved: () => void; setError: (s: string) => void }) {
  const [limit, setLimit] = useState(sw.license_limit?.toString() ?? "");
  const dirty = limit !== (sw.license_limit?.toString() ?? "");
  return (
    <tr>
      <td>{sw.name}</td>
      <td>
        <div className="row" style={{ flexWrap: "nowrap" }}>
          <input style={{ maxWidth: 120 }} type="number" min={0} placeholder="제한 없음" value={limit} onChange={(e) => setLimit(e.target.value)} />
          <button
            className="btn sm primary"
            disabled={!dirty}
            onClick={() =>
              act(
                () =>
                  api(`/api/admin/software/${sw.id}`, {
                    method: "PATCH",
                    json: limit === "" ? { clear_license_limit: true } : { license_limit: Number(limit) },
                  }),
                setError,
                onSaved,
              )
            }
          >
            저장
          </button>
        </div>
      </td>
    </tr>
  );
}

// ------------------------------------------------------------------ 사용자
function UsersTab() {
  const { data, error, setError, reload } = useLoad<AdminUser[]>("/api/admin/users");
  const [u, setU] = useState({ username: "", display_name: "", password: "", role: "student" });

  return (
    <div className="stack">
      {error && <div className="alert error">{error}</div>}
      <div className="card">
        <h2>사용자 추가</h2>
        <p className="muted small" style={{ marginTop: 0 }}>
          학교 SSO 연동 전 시범 운영용 계정입니다. 여러 명은 서버에서 <code>python -m app.cli import-users users.csv</code> 로 한
          번에 등록할 수 있습니다.
        </p>
        <div className="grid">
          <input placeholder="아이디 (학번)" value={u.username} onChange={(e) => setU({ ...u, username: e.target.value })} />
          <input placeholder="이름" value={u.display_name} onChange={(e) => setU({ ...u, display_name: e.target.value })} />
          <input
            type="password"
            placeholder="초기 비밀번호 (8자 이상)"
            value={u.password}
            onChange={(e) => setU({ ...u, password: e.target.value })}
          />
          <select value={u.role} onChange={(e) => setU({ ...u, role: e.target.value })}>
            <option value="student">학생</option>
            <option value="admin">관리자</option>
          </select>
        </div>
        <button
          className="btn primary"
          style={{ marginTop: 12 }}
          disabled={!u.username || u.password.length < 8}
          onClick={() =>
            act(() => api("/api/admin/users", { method: "POST", json: u }), setError, () => {
              setU({ username: "", display_name: "", password: "", role: "student" });
              reload();
            })
          }
        >
          추가
        </button>
      </div>
      <div className="card table-wrap">
        <table>
          <thead>
            <tr>
              <th>아이디</th>
              <th>이름</th>
              <th>권한</th>
              <th>상태</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data?.map((x) => (
              <tr key={x.id}>
                <td className="mono">{x.username}</td>
                <td>{x.display_name}</td>
                <td>{x.role === "admin" ? <span className="badge warn">관리자</span> : "학생"}</td>
                <td>{x.is_active ? "사용" : <span className="badge">정지</span>}</td>
                <td>
                  <button
                    className="btn sm"
                    onClick={() =>
                      act(
                        () => api(`/api/admin/users/${x.id}`, { method: "PATCH", json: { is_active: !x.is_active } }),
                        setError,
                        reload,
                      )
                    }
                  >
                    {x.is_active ? "정지" : "해제"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ 로그
const ACTION_LABEL: Record<string, string> = {
  login: "로그인",
  login_failed: "로그인 실패",
  session_start: "PC 배정",
  session_ready: "PC 준비 완료",
  session_end: "세션 종료",
  session_failed: "세션 실패",
  connect: "원격 접속",
  wake_error: "켜기 오류",
};

function AuditTab() {
  const { data, error } = useLoad<Audit[]>("/api/admin/audit?limit=300", 15000);
  return (
    <div className="stack">
      {error && <div className="alert error">{error}</div>}
      <div className="card table-wrap">
        <table>
          <thead>
            <tr>
              <th>시각</th>
              <th>사용자</th>
              <th>동작</th>
              <th>내용</th>
              <th>IP</th>
            </tr>
          </thead>
          <tbody>
            {data?.map((a) => (
              <tr key={a.id}>
                <td className="small" style={{ whiteSpace: "nowrap" }}>
                  {new Date(a.at).toLocaleString("ko-KR")}
                </td>
                <td>{a.username || "-"}</td>
                <td>{ACTION_LABEL[a.action] ?? a.action}</td>
                <td className="mono small" style={{ maxWidth: 420, wordBreak: "break-all" }}>
                  {a.detail}
                </td>
                <td className="mono small">{a.ip}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
