# 2단계 배포 — 포털 + 원격 접속 게이트웨이

학생이 포털에서 프로그램을 고르면 비어 있는 실습실 PC 를 배정하고, 꺼져 있으면 WoL 로 켠 뒤, 브라우저(Guacamole)로 접속시켜 줍니다.

```
[학생 브라우저] --443--> nginx ─ /            포털 화면 (정적 파일)
                               ─ /api/        api: 로그인, PC 배정, 상태 확인, WoL 요청
                               ─ /guacamole/  guacamole → guacd ──3389──> 실습실 PC
api ──HTTP──> WoL 릴레이 (실습실 VLAN 안) ──매직 패킷──> 실습실 PC
api ──TCP 3389 확인──> 실습실 PC (10초마다, 켜짐/꺼짐 판단)
```

1단계(`infra/poc`)와 달라진 점
- Guacamole 에 학생 계정이나 연결을 등록하지 않습니다. 포털이 세션마다 **1회용 암호화 접속 정보**(Guacamole encrypted JSON 인증)를 만들어 넘기므로, 학생은 PC 주소를 모르고 배정받은 PC 한 대에만 접속할 수 있습니다.
- Guacamole 의 TOTP·DB 는 쓰지 않습니다. 로그인은 포털이 담당합니다.

## 1. 준비
| 항목 | 내용 |
|---|---|
| 서버 | 교내 DMZ Linux VM (2 vCPU / 4GB / 40GB), Docker + Compose |
| 방화벽 | 외부 → 서버 443/80, 서버 → 실습실 VLAN TCP 3389, 서버 → WoL 릴레이 TCP 8080 |
| 실습실 PC | [IT 설정 가이드](../../docs/it-setup-guide.md) 완료 |
| WoL 릴레이 | 실습실 VLAN 마다 1대 (아래 4번) |

## 2. 설치
저장소 루트가 빌드 컨텍스트이므로 이 디렉터리에서 실행합니다.
```bash
cd infra/stack
cp .env.example .env
```
`.env` 의 빈 값을 채웁니다.
```bash
openssl rand -base64 32
```
```bash
openssl rand -hex 16
```
위 명령으로 `POSTGRES_PASSWORD`, `JARION_DB_PASSWORD`, `JARION_JWT_SECRET`, `RELAY_TOKEN` 은 base64 값, `GUAC_JSON_SECRET_KEY` 는 **반드시 hex 32자리** 값을 넣습니다.

인증서 (`certs/server.crt`, `certs/server.key`) 를 넣습니다. 시험용은 1단계의 `infra/poc/scripts/gen-selfsigned-cert.sh` 로 만든 뒤 복사해도 됩니다.

```bash
docker compose up -d --build
```
```bash
docker compose ps
```

## 3. 관리자 계정 만들기
```bash
docker compose exec api python -m app.cli create-user admin --admin --name 관리자
```
`https://<서버>/` 에서 로그인 → 오른쪽 위 **관리**.

## 4. WoL 릴레이 설치 (실습실 VLAN 마다)
라즈베리파이 등 실습실 PC 와 같은 VLAN 에 상시 켜진 Linux 장비에서:
```bash
sudo mkdir -p /opt/jarion
```
```bash
sudo cp tools/wol/wol.py tools/wol/relay.py /opt/jarion/
```
```bash
sudo cp tools/wol/jarion-wol-relay.service /etc/systemd/system/
```
서비스 파일의 `--allow-from`(포털 서버 IP), `--broadcast`(실습실 브로드캐스트 주소)를 바꾸고, 토큰을 넣습니다.
```bash
sudo systemctl edit jarion-wol-relay
```
열린 편집기에 아래를 넣습니다 (`.env` 의 `RELAY_TOKEN` 과 같은 값).
```
[Service]
Environment=RELAY_TOKEN=여기에_토큰
```
```bash
sudo systemctl enable --now jarion-wol-relay
```

## 5. 관리 화면에서 초기 설정
1. **실습실·프로그램** 탭
   - 실습실 추가: 이름, 브로드캐스트 주소(예: `10.20.30.255`), 릴레이 URL(예: `http://10.20.30.5:8080`)
   - 프로그램 추가: `Revit`, `MIDAS` 등. **동시 사용 라이선스 수**를 넣으면 그 이상은 배정하지 않습니다.
     - CSV 가져오기 시 PC 에 설치된 프로그램 이름에 이 이름이 포함되면 자동 연결됩니다 (예: `Revit` ↔ `Autodesk Revit 2025`).
2. **PC** 탭 → CSV 가져오기: 각 PC 에서 `Setup-LabPC.ps1` 로 만든 CSV 를 올립니다.
3. **사용자** 탭: 시범 운영 학생 계정 추가. 많으면 CSV(`username,display_name,password[,role]`)로:
   ```bash
   docker compose cp users.csv api:/tmp/users.csv
   ```
   ```bash
   docker compose exec api python -m app.cli import-users /tmp/users.csv
   ```

## 6. 동작 방식 / 정책
| 상황 | 동작 |
|---|---|
| 학생이 프로그램 선택 | 켜져 있고 빈 PC(가장 오래 안 쓴 것) 우선 배정 → 바로 "접속하기" |
| 빈 PC 가 모두 꺼져 있음 | WoL 전송 → 90초마다 재전송(최대 3회) → RDP 포트가 열리면 접속 가능 |
| 5분 안에 안 켜짐 | 세션 실패 처리, 해당 PC 는 30분간 배정 제외, 학생에게 재시도 안내 |
| 배정 후 15분 안에 접속 안 함 | 자동 반납 |
| 최대 사용 시간 (기본 4시간) | 자동 반납 |
| 라이선스 수 초과 | 배정 거부 |
| 한 학생 | 동시에 PC 1대만 |

모든 로그인, 배정, 접속, 종료, 켜기 오류는 **로그** 탭에 남습니다.

## 7. PC 에이전트
`.env` 에 `AGENT_ENROLLMENT_KEY` 를 넣고 각 PC 에 에이전트를 설치하면 아래가 추가로 동작합니다. 설치 방법은 [agent/README.md](../../agent/README.md).

| 상황 | 동작 |
|---|---|
| PC 앞에 누가 로그인해 있음 | 원격 배정하지 않음 |
| 학생이 반납 | 원격 세션 즉시 로그오프 |
| 시간 만료 / 관리자 종료 | 원격 화면에 안내 → 1분 뒤 로그오프 |
| 종료 10분 전 | 원격 화면에 안내 |
| 브라우저를 닫고 15분 방치 | 자동 반납·로그오프 |
| 원격 PC 에서 직접 로그오프 | 5분 뒤 자동 반납 |
| 포털 배정 없이 남은 원격 세션 | 로그오프 (`AGENT_EXEMPT_USERS` 계정 제외) |
| 유휴 PC (선택) | `IDLE_SHUTDOWN_MINUTES` 분 뒤 종료 |

에이전트가 없는 PC 는 기존처럼 동작합니다 (반납해도 Windows 세션이 남고, 현장 사용자를 감지하지 못함).

## 8. 현재 한계
- 로그인은 포털 자체 계정입니다. 학교 SSO 연동은 학교 측 방식(SAML/OIDC/LDAP) 확인 후 추가합니다.
- DB 구조 변경은 아직 자동 마이그레이션이 없습니다. 시범 운영 전에 Alembic 을 도입할 예정이며, 그 전까지 버전을 올릴 때는 DB 를 새로 만들어야 할 수 있습니다.
- api 는 스케줄러를 내장하므로 **컨테이너 1개, 워커 1개**로만 실행해야 합니다.

## 운영 명령
```bash
docker compose logs -f api
```
```bash
docker compose exec postgres pg_dump -U postgres jarion > jarion-backup.sql
```
