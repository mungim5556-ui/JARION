"use client";

import { useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import {
  api,
  ApiError,
  fmtRemaining,
  fmtTime,
  openRemote,
  type LabSummary,
  type RemoteSession,
  type SoftwareAvailability,
} from "@/lib/api";

type Catalog = { software: SoftwareAvailability[]; labs: LabSummary[] };
type Current = { session: RemoteSession | null; last: RemoteSession | null };

function useNow(intervalMs = 1000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);
  return now;
}

export default function Home() {
  return (
    <Shell>
      <Dashboard />
    </Shell>
  );
}

function Dashboard() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [current, setCurrent] = useState<Current | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [c, s] = await Promise.all([api<Catalog>("/api/catalog"), api<Current>("/api/sessions/current")]);
      setCatalog(c);
      setCurrent(s);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) window.location.href = "/login/";
    }
  }, []);

  const waking = current?.session?.status === "waking";
  useEffect(() => {
    refresh();
    const t = setInterval(refresh, waking ? 3000 : 15000);
    return () => clearInterval(t);
  }, [refresh, waking]);

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "요청에 실패했습니다");
    } finally {
      setBusy(false);
      refresh();
    }
  }

  const start = (softwareId: number) => run(() => api("/api/sessions", { method: "POST", json: { software_id: softwareId } }));
  const connect = (id: number) => run(() => openRemote(id));
  const end = (id: number) => {
    if (!confirm("PC 를 반납할까요? 저장하지 않은 작업은 사라질 수 있습니다.")) return;
    run(() => api(`/api/sessions/${id}/end`, { method: "POST" }));
  };

  if (!catalog || !current) return <p className="muted">불러오는 중…</p>;

  return (
    <div className="stack">
      <div>
        <h1>원격 실습실</h1>
        <p className="sub">필요한 프로그램을 고르면 비어 있는 실습실 PC 를 배정해 드립니다.</p>
      </div>

      {error && <div className="alert error">{error}</div>}

      {current.session ? (
        <SessionCard s={current.session} busy={busy} onConnect={connect} onEnd={end} />
      ) : (
        <>
          {current.last && current.last.status === "failed" && (
            <div className="alert warn">
              {current.last.machine_name} PC 가 켜지지 않았습니다. 다른 PC 로 다시 시도해 주세요.
            </div>
          )}
          <section>
            <h2>프로그램 선택</h2>
            {catalog.software.length === 0 ? (
              <div className="alert info">등록된 프로그램이 없습니다. 관리자에게 문의하세요.</div>
            ) : (
              <div className="grid">
                {catalog.software.map((sw) => (
                  <SoftwareCard key={sw.id} sw={sw} busy={busy} onStart={start} />
                ))}
              </div>
            )}
          </section>
        </>
      )}

      <section>
        <h2>실습실 현황</h2>
        <div className="grid">
          {catalog.labs.map((lab) => (
            <div key={lab.id} className="card">
              <div style={{ fontWeight: 700 }}>{lab.name}</div>
              {lab.location && <div className="muted small">{lab.location}</div>}
              <div className="row small" style={{ marginTop: 8 }}>
                <span className="badge">전체 {lab.total}</span>
                <span className="badge ok">켜짐 {lab.online}</span>
                <span className="badge warn">사용 중 {lab.in_use}</span>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function SoftwareCard({
  sw,
  busy,
  onStart,
}: {
  sw: SoftwareAvailability;
  busy: boolean;
  onStart: (id: number) => void;
}) {
  const licenseFull = sw.license_limit !== null && sw.license_in_use >= sw.license_limit;
  const free = sw.available_now + sw.wakeable;
  const disabled = busy || licenseFull || free === 0;

  let status: React.ReactNode;
  if (licenseFull) status = <span className="badge danger">라이선스 모두 사용 중</span>;
  else if (sw.available_now > 0) status = <span className="badge ok"><span className="dot" />바로 접속 {sw.available_now}대</span>;
  else if (sw.wakeable > 0) status = <span className="badge warn"><span className="dot" />켜서 접속 (1~3분)</span>;
  else status = <span className="badge">빈 PC 없음</span>;

  return (
    <div className="card sw-card">
      <div className="name">{sw.name}</div>
      <div className="row">{status}</div>
      <div className="meta">
        설치 PC {sw.total}대 · 사용 중 {sw.in_use}대
        {sw.license_limit !== null && ` · 라이선스 ${sw.license_in_use}/${sw.license_limit}`}
      </div>
      <button className="btn primary" disabled={disabled} onClick={() => onStart(sw.id)}>
        사용하기
      </button>
    </div>
  );
}

function SessionCard({
  s,
  busy,
  onConnect,
  onEnd,
}: {
  s: RemoteSession;
  busy: boolean;
  onConnect: (id: number) => void;
  onEnd: (id: number) => void;
}) {
  const now = useNow();

  if (s.status === "waking") {
    const elapsed = Math.max(0, (now - new Date(s.created_at).getTime()) / 1000);
    const pct = Math.min(95, (elapsed / s.boot_timeout_seconds) * 100);
    return (
      <div className="card session-card waking stack">
        <div className="row">
          <span className="badge warn"><span className="dot" />PC 켜는 중</span>
          <strong>{s.machine_name}</strong>
          <span className="muted small">{s.lab_name}</span>
        </div>
        <div className="progress"><div style={{ width: `${pct}%` }} /></div>
        <div className="muted small">
          {Math.floor(elapsed)}초 경과 · 보통 1~3분 걸립니다. 이 화면을 열어 두면 준비되는 즉시 접속 버튼이 켜집니다.
        </div>
        <div className="row">
          <button className="btn danger" disabled={busy} onClick={() => onEnd(s.id)}>
            취소
          </button>
        </div>
      </div>
    );
  }

  const remaining = s.expires_at ? new Date(s.expires_at).getTime() - now : 0;
  return (
    <div className="card session-card ready stack">
      <div className="row">
        <span className="badge ok"><span className="dot" />접속 가능</span>
        <strong>{s.machine_name}</strong>
        <span className="muted small">{s.lab_name}</span>
      </div>
      <dl className="kv">
        <dt>프로그램</dt>
        <dd>{s.software_name ?? "-"}</dd>
        <dt>남은 시간</dt>
        <dd>{fmtRemaining(remaining)} (종료 {fmtTime(s.expires_at)})</dd>
        {!s.connected_at && (
          <>
            <dt>안내</dt>
            <dd>15분 안에 접속하지 않으면 자동 반납됩니다.</dd>
          </>
        )}
      </dl>
      <div className="row">
        <button className="btn primary big" disabled={busy} onClick={() => onConnect(s.id)}>
          {s.connected_at ? "다시 접속" : "접속하기"}
        </button>
        <button className="btn danger" disabled={busy} onClick={() => onEnd(s.id)}>
          반납하기
        </button>
      </div>
      <div className="alert info small">
        Windows 로그인 창이 나오면 <b>학교 계정</b>으로 로그인하세요. 작업 파일은 PC 가 아닌 <b>개인 네트워크 드라이브</b>에
        저장하세요. 공용 PC 라 반납 후 PC 에 남은 파일은 지워질 수 있습니다.
      </div>
    </div>
  );
}

