# JARION 원격 실습실

학교 밖에서 실습실 PC 를 원격으로 켜고 브라우저로 접속해, 학교 IP 에서만 라이선스가 확인되는 Revit·MIDAS 등을 쓰게 해 주는 서비스입니다. 프로그램은 교내 PC 에서 실행되므로 라이선스는 지금처럼 학교 안에서 확인됩니다.

- 전체 계획: [docs/PLAN.md](docs/PLAN.md)
- IT팀 PC 설정 가이드: [docs/it-setup-guide.md](docs/it-setup-guide.md)

## 구성
| 경로 | 내용 | 단계 |
|---|---|---|
| `infra/poc/` | Guacamole 단독 시험 구축 (수동 연결 등록) | 1단계 |
| `scripts/windows/Setup-LabPC.ps1` | 실습실 PC 설정 (RDP, 방화벽, WoL, GPU 정책, 등록 CSV) | 1단계 |
| `scripts/windows/Install-JarionAgent.ps1` | PC 에이전트 설치/업데이트 (GPO 시작 스크립트용) | 2단계 |
| `tools/wol/` | WoL 전송 도구 `wol.py`, 실습실 VLAN 용 릴레이 `relay.py` | 1·2단계 |
| `apps/api/` | 포털 백엔드 (FastAPI): 로그인, PC 배정, 상태 확인, WoL, Guacamole 접속 토큰 | 2단계 |
| `agent/` | PC 에이전트 (Go, Windows 서비스): 상태 보고, 반납 시 로그오프, 현장 사용자 감지 — [설명](agent/README.md) | 2단계 |
| `apps/web/` | 포털 화면 (Next.js 정적 빌드): 학생 화면, 관리 화면 | 2단계 |
| `infra/stack/` | 2단계 배포 (nginx + api + postgres + guacamole) — [설치 안내](infra/stack/README.md) | 2단계 |

## 개발 환경
백엔드 (SQLite 로 바로 실행, 포트 8000):
```bash
cd apps/api
```
```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
```
```bash
.venv/bin/pytest
```
```bash
JARION_COOKIE_SECURE=false JARION_GUAC_JSON_SECRET_KEY=0123456789abcdef0123456789abcdef .venv/bin/uvicorn app.main:app_factory --factory --reload
```
관리자 계정:
```bash
.venv/bin/python -m app.cli create-user admin --admin
```

포털 화면 (포트 3000, `/api` 는 8000 으로 프록시):
```bash
cd apps/web && npm install && npm run dev
```

API 문서: 백엔드 실행 후 `http://localhost:8000/api/docs`
