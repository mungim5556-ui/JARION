# JARION PC 에이전트

실습실 PC 마다 설치하는 작은 Windows 서비스입니다. 15초마다 포털에 PC 상태를 보고하고, 포털이 보낸 명령을 실행합니다. **PC 쪽에 들어오는 포트를 열 필요가 없습니다** (PC → 포털 HTTPS 만 사용).

## 하는 일
| 기능 | 내용 |
|---|---|
| 상태 보고 | 로그인한 사람(현장 / 원격 RDP / 연결 끊김), 감시 대상 프로그램(Revit, MIDAS 등) 실행 여부 |
| 현장 사용자 감지 | PC 앞에 누가 로그인해 있으면 포털이 그 PC 를 원격 배정하지 않음 |
| 반납 시 로그오프 | 학생이 반납하면 즉시, 시간 만료·관리자 종료면 안내 메시지 후 1분 뒤 원격 세션 로그오프 |
| 종료 임박 안내 | 사용 시간 10분 전에 원격 화면에 메시지 |
| 방치 세션 정리 | 브라우저를 닫고 15분 지나면 자동 반납·로그오프, 원격 PC 에서 직접 로그오프하면 5분 뒤 반납 |
| 포털 밖 접속 정리 | 포털 배정 없이 남아 있는 원격 세션은 로그오프 (제외 계정 제외) |
| 유휴 PC 종료 (선택) | 아무도 안 쓰는 PC 를 N분 뒤 종료 (`IDLE_SHUTDOWN_MINUTES`, 기본 꺼짐) |

## 안전 원칙 (코드로 강제)
- 로그오프·메시지는 **원격(RDP) 세션에만**. PC 앞에 앉은 사람(콘솔 세션)은 절대 로그오프하지 않습니다.
- `AGENT_EXEMPT_USERS` 에 넣은 계정(IT 관리자 등)은 로그오프하지 않습니다.
- 종료 명령은 **로그인한 사람이 한 명이라도 있으면 거부**합니다.
- 포털이 정해 둔 명령(message / logoff / shutdown) 외에는 실행하지 않습니다. 임의 명령 실행 기능이 없습니다.

## 등록 방식
모든 PC 에 **같은 설정**(포털 주소 + 공통 등록 키)을 배포하면 됩니다. 에이전트가 처음 시작할 때 자기 PC 이름과 MAC 주소를 보내고, 포털에 같은 이름·MAC 으로 등록된 PC 가 있으면 그 PC 전용 토큰을 받아 `C:\ProgramData\JARION\token` 에 저장합니다. 그래서 포털에 PC 가 먼저 등록되어 있어야 합니다 (관리 화면 → PC → CSV 가져오기).

PC 를 교체하거나 토큰이 유출된 것 같으면 관리 화면 PC 탭의 **토큰 폐기** 버튼을 누르면 됩니다. 에이전트는 자동으로 다시 등록합니다.

## 빌드
Go 1.22 이상. Linux/macOS 에서도 Windows 용으로 교차 컴파일됩니다.
```bash
cd agent
```
```bash
VERSION=0.1.0 ./build.sh
```
결과: `agent/dist/jarion-agent.exe`

테스트:
```bash
go test ./...
```

## 설치
1. 포털 `.env` 에 `AGENT_ENROLLMENT_KEY` 를 설정하고 포털을 재시작합니다.
2. `jarion-agent.exe` 와 `scripts/windows/Install-JarionAgent.ps1` 을 IT 공유 폴더에 둡니다.
3. PC 에서 관리자 PowerShell 로 (또는 GPO 컴퓨터 시작 스크립트로):
```powershell
.\Install-JarionAgent.ps1 -Source \\nas\it\jarion\jarion-agent.exe -ApiUrl https://remote.school.ac.kr -EnrollmentKey "<등록 키>"
```
같은 버전이 이미 설치되어 있으면 아무것도 하지 않으므로, GPO 로 매 부팅마다 실행해 두면 새 버전 exe 를 공유 폴더에 올리는 것만으로 업데이트됩니다.

수동 명령:
```powershell
& "C:\Program Files\JARION\jarion-agent.exe" sessions
```
```powershell
& "C:\Program Files\JARION\jarion-agent.exe" uninstall
```

## 문제 확인
| 증상 | 확인 |
|---|---|
| 관리 화면에 "미설치" | `C:\ProgramData\JARION\agent.log` 확인. "포털에 등록되지 않은 PC" → 포털 PC 이름이 Windows 컴퓨터 이름과 같은지. "MAC 주소가 다릅니다" → 포털에 등록된 MAC 확인 |
| "응답 없음" | PC 가 꺼졌거나, PC → 포털 443 방화벽, 인증서 문제 (로그에 x509 오류면 설치 시 `-CaFile` 지정) |
| 현장 사용자가 계속 표시됨 | PC 앞에서 로그인한 채 잠가 둔 경우입니다. 로그오프해야 원격 배정됩니다 |
| `sessions` 결과가 이상함 | 결과 JSON 을 개발팀에 전달 |

## 구조
```
cmd/jarion-agent/        명령줄 (install / uninstall / run / sessions / version), 서비스 진입점
internal/agent/          보고·명령 실행 로직 (운영체제 독립, 테스트 있음)
internal/system/         Windows API (WTS 세션 조회·로그오프·메시지, 프로세스 목록, 종료)
internal/client/         포털 API 호출
internal/config/         설정·토큰 파일
internal/service/        Windows 서비스 등록/실행
```
