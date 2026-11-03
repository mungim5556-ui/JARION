# 1단계 PoC — Guacamole 게이트웨이 설치

목표: 학교 밖에서 브라우저로 실습실 PC 3~5대에 접속해 **Revit/MIDAS 실행 + 라이선스 정상 체크아웃 + 체감 성능**을 확인한다.
(포털·자동 배정은 2단계. PoC 에서는 Guacamole 관리 화면에서 연결을 수동 등록한다.)

```
[학교 밖 브라우저] --443--> [nginx] -> [guacamole] -> [guacd] --3389--> [실습실 PC]
                         (교내 DMZ 서버, docker)              (실습실 VLAN)
```

## 0. 준비물
| 항목 | 내용 |
|---|---|
| 서버 | 교내 DMZ 의 Linux VM 1대 (2 vCPU / 4GB RAM / 40GB, Ubuntu 22.04/24.04 권장), Docker + Compose 플러그인 |
| 네트워크 | 외부 → 서버 443(80) 허용 / 서버 → 실습실 VLAN TCP 3389 허용 |
| 도메인 | 예: `remote.<학교도메인>` → 서버 공인 IP (PoC 는 IP 직접 접속도 가능) |
| 실습실 PC | [IT 설정 가이드](../../docs/it-setup-guide.md) 완료된 PC 3~5대 |

## 1. 설치
```bash
cd infra/poc
cp .env.example .env
```
`.env` 의 `POSTGRES_PASSWORD` 를 긴 임의 값으로 바꾼다 (`openssl rand -base64 24`).

```bash
./scripts/init-db.sh
```
```bash
./scripts/gen-selfsigned-cert.sh remote.example.ac.kr
```
```bash
docker compose up -d
```
```bash
docker compose ps
```

> 운영 인증서가 있으면 `certs/server.crt`, `certs/server.key` 로 넣으면 된다 (체인 포함 crt).

## 2. 최초 로그인 & 관리자 계정 정리
1. `https://<서버>/guacamole/` 접속, 기본 계정 `guacadmin` / `guacadmin` 으로 로그인
2. TOTP 가 켜져 있으므로 휴대폰 OTP 앱으로 QR 등록
3. **설정 → 사용자** 에서 새 관리자 계정을 만들고(모든 권한 체크), 그 계정으로 다시 로그인한 뒤 `guacadmin` 을 **삭제**

## 3. 실습실 PC 연결 등록 (PC 마다)
**설정 → 연결 → 새 연결**

| 항목 | 값 |
|---|---|
| 이름 | `LAB301-PC07` 등 (PC 이름과 동일하게) |
| 프로토콜 | RDP |
| 네트워크 → 호스트 이름 | PC IP (`Setup-LabPC.ps1` 이 만든 CSV 참고) |
| 네트워크 → 포트 | 3389 |
| 인증 → 사용자명/비밀번호 | **비워 둠** (PoC 에서는 학생이 접속 시 본인 학교 계정 입력) |
| 인증 → 보안 모드 | NLA |
| 인증 → 서버 인증서 무시 | 체크 (도메인 내부 인증서 미배포 시) |
| 디스플레이 → 크기 조정 방법 | `display-update` (브라우저 크기에 맞춰 해상도 변경) |
| 디스플레이 → 색 농도 | True color (32-bit) |
| 성능 → 글꼴 다듬기 | 체크 |
| 장치 리디렉션 → 클립보드 | PoC 측정 항목에 따라 결정 (기본은 허용, 운영 정책은 IT팀과 결정) |
| 화면 녹화 (선택) | 경로 `${HISTORY_PATH}/${HISTORY_UUID}`, "경로 자동 생성" 체크 → 감사용 녹화 |

PoC 테스트 학생 계정을 **설정 → 사용자** 에서 만들고 해당 연결에 권한을 준다.
(학교 계정 연동(LDAP/SAML/OIDC)은 2단계에서 적용)

## 4. 깨우기 → 접속 테스트
PC 가 꺼져 있으면 실습실 VLAN 안의 장비에서:
```bash
python3 tools/wol/wol.py AA:BB:CC:DD:EE:FF --broadcast 10.20.30.255
```
1~2분 후 Guacamole 에서 연결 클릭 → 학교 계정으로 로그인.

## 5. PoC 측정 체크리스트
교외 네트워크(가정 인터넷, 모바일 핫스팟 두 가지)에서 측정한다.

- [ ] WoL: 완전 종료(S5) 상태에서 깨우기 성공률 (PC 별 10회)
- [ ] 깨우기 → 로그인 화면까지 소요 시간
- [ ] Revit 실행 → **라이선스 정상 체크아웃** (오류 메시지·라이선스 서버 로그 확인)
- [ ] MIDAS 실행 → 라이선스 정상 확인
- [ ] Revit 3D 뷰 회전 시 체감 지연/프레임 (작업관리자 GPU 사용률이 올라가는지 = GPU 정책 적용 확인)
- [ ] 1920x1080 / 2560x1440 각각 사용 대역폭 (서버 `docker stats`, `iftop`)
- [ ] 동시 접속 3~5명일 때 서버 CPU/메모리
- [ ] 브라우저별 (Chrome, Edge, Safari, 태블릿) 동작
- [ ] 한글 입력, 단축키(Ctrl+Z, 휠 클릭 팬 등) 동작
- [ ] 세션 끊김 후 재접속 시 작업 유지 여부
- [ ] 저장 파일 위치: 홈 드라이브/NAS 로 저장되는지

결과가 부족하면(특히 3D 회전 체감) 2단계에서 네이티브 RDP(RD Gateway) 또는 저지연 스트리밍(Sunshine/Moonlight 등) 경로를 추가 검토한다.

## 운영 명령
```bash
docker compose logs -f guacamole
```
```bash
docker compose down
```
초기화(DB 포함 전부 삭제)가 필요할 때만:
```bash
docker compose down -v
```
