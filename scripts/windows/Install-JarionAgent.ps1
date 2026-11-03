<#
.SYNOPSIS
    JARION PC 에이전트 설치/업데이트 (관리자 권한, 또는 GPO 컴퓨터 시작 스크립트).

.DESCRIPTION
    1. jarion-agent.exe 를 C:\Program Files\JARION\ 으로 복사
    2. 이미 같은 버전이 설치되어 있으면 아무것도 하지 않음 (GPO 로 매 부팅마다 실행해도 안전)
    3. 다른 버전이면 기존 서비스를 지우고 새로 설치
    4. 서비스(JarionAgent) 등록 -> 자동 시작, 실패 시 자동 재시작
       설정·토큰은 C:\ProgramData\JARION\ (SYSTEM/Administrators 만 접근)

.PARAMETER Source
    jarion-agent.exe 위치 (공유 폴더 가능). 예: \\nas\it\jarion\jarion-agent.exe

.PARAMETER ApiUrl
    포털 주소. 예: https://remote.school.ac.kr

.PARAMETER EnrollmentKey
    포털 .env 의 AGENT_ENROLLMENT_KEY 와 같은 값

.PARAMETER CaFile
    (선택) 포털이 자체 서명 인증서를 쓰는 경우 그 인증서(PEM) 경로

.EXAMPLE
    .\Install-JarionAgent.ps1 -Source \\nas\it\jarion\jarion-agent.exe -ApiUrl https://remote.school.ac.kr -EnrollmentKey (Get-Content \\nas\it\jarion\enroll.key)
#>
#Requires -RunAsAdministrator
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Source,
    [Parameter(Mandatory = $true)][string]$ApiUrl,
    [Parameter(Mandatory = $true)][string]$EnrollmentKey,
    [string]$CaFile = ''
)

$ErrorActionPreference = 'Stop'
$installDir = Join-Path $env:ProgramFiles 'JARION'
$target = Join-Path $installDir 'jarion-agent.exe'
$serviceName = 'JarionAgent'

if (-not (Test-Path $Source)) { throw "에이전트 파일을 찾을 수 없습니다: $Source" }
$newVersion = (& $Source version).Trim()

$svc = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
if ($svc -and (Test-Path $target)) {
    $curVersion = (& $target version).Trim()
    if ($curVersion -eq $newVersion) {
        if ($svc.Status -ne 'Running') { Start-Service $serviceName }
        Write-Host "이미 최신 버전($curVersion)이 설치되어 있습니다."
        return
    }
    Write-Host "업데이트: $curVersion -> $newVersion"
}

if ($svc) {
    & $target uninstall | Out-Host
}

New-Item -ItemType Directory -Path $installDir -Force | Out-Null
Copy-Item -Path $Source -Destination $target -Force

$installArgs = @('install', '--api', $ApiUrl, '--key', $EnrollmentKey)
if ($CaFile) { $installArgs += @('--ca', $CaFile) }
& $target @installArgs | Out-Host
if ($LASTEXITCODE -ne 0) { throw "jarion-agent install 실패 (exit $LASTEXITCODE)" }

Start-Sleep -Seconds 5
$log = Join-Path $env:ProgramData 'JARION\agent.log'
if (Test-Path $log) { Get-Content $log -Tail 5 }
Write-Host "설치 완료 ($newVersion). 포털 관리 화면 PC 탭에서 '에이전트: 정상' 을 확인하세요."
