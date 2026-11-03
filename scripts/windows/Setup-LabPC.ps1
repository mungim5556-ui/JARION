<#
.SYNOPSIS
    JARION 원격 접속 PoC 용 실습실 PC 설정 스크립트.

.DESCRIPTION
    관리자 권한 PowerShell 에서 실행한다. 수행 내용:
      1. 원격 데스크톱(RDP) 활성화 + NLA(네트워크 수준 인증) 강제
      2. Windows 기본 RDP 방화벽 규칙을 끄고, 게이트웨이 IP 에서 오는 3389만 허용
      3. 빠른 시작(Fast Startup)·최대 절전 끄기 (WoL 이 S5 에서 동작하도록)
      4. 네트워크 어댑터 Wake-on-LAN(매직 패킷) 활성화
      5. RDP 세션에서 GPU 사용 정책 적용 (Revit/MIDAS 3D 뷰포트용)
      6. 원격 접속 허용 그룹 등록 (선택)
      7. 등록용 정보(PC 이름/MAC/IP/GPU)를 CSV 로 출력

    BIOS/UEFI 의 Wake-on-LAN 설정은 스크립트로 바꿀 수 없으므로 docs/it-setup-guide.md 를 따른다.

.PARAMETER GatewayIP
    Guacamole(guacd) 서버의 IP 또는 CIDR. 쉼표로 여러 개 가능. 예: 10.0.5.20  또는 10.0.5.0/28

.PARAMETER RemoteUsers
    원격 데스크톱 사용자 그룹에 추가할 계정/그룹. 예: "SCHOOL\LabRemoteUsers"

.PARAMETER OutputCsv
    등록 정보를 덧붙일 CSV 경로 (공유 폴더 가능). 기본: 바탕화면\jarion-lab-pc.csv

.PARAMETER WhatIf
    실제로 바꾸지 않고 할 일만 출력.

.EXAMPLE
    .\Setup-LabPC.ps1 -GatewayIP 10.0.5.20 -RemoteUsers "SCHOOL\LabRemoteUsers" -OutputCsv \\nas\it\jarion\lab-pc.csv
#>
#Requires -RunAsAdministrator
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)][string[]]$GatewayIP,
    [string[]]$RemoteUsers = @(),
    [string]$OutputCsv = (Join-Path ([Environment]::GetFolderPath('Desktop')) 'jarion-lab-pc.csv')
)

$ErrorActionPreference = 'Stop'
function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }

# ---------------------------------------------------------------- 1. RDP + NLA
Step '1. 원격 데스크톱 활성화 (NLA 필수)'
$ts = 'HKLM:\System\CurrentControlSet\Control\Terminal Server'
if ($PSCmdlet.ShouldProcess('Terminal Server', 'fDenyTSConnections=0, UserAuthentication=1')) {
    Set-ItemProperty -Path $ts -Name fDenyTSConnections -Value 0
    Set-ItemProperty -Path "$ts\WinStations\RDP-Tcp" -Name UserAuthentication -Value 1
}

# ---------------------------------------------------------------- 2. 방화벽
Step '2. 방화벽: 게이트웨이에서 오는 RDP(3389)만 허용'
# 기본 '원격 데스크톱' 규칙 그룹(모든 IP 허용)을 끈다. 리소스 문자열로 지정해 한글/영문 Windows 모두 동작.
$rdpGroup = '@FirewallAPI.dll,-28752'
if ($PSCmdlet.ShouldProcess('기본 원격 데스크톱 방화벽 규칙', 'Disable')) {
    Get-NetFirewallRule -Group $rdpGroup -ErrorAction SilentlyContinue | Disable-NetFirewallRule
}
$ruleName = 'JARION-RDP-from-Gateway'
if ($PSCmdlet.ShouldProcess($ruleName, "Allow TCP 3389 from $($GatewayIP -join ',')")) {
    Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    New-NetFirewallRule -Name $ruleName -DisplayName 'JARION RDP (게이트웨이 전용)' `
        -Direction Inbound -Protocol TCP -LocalPort 3389 -RemoteAddress $GatewayIP `
        -Action Allow -Profile Any | Out-Null
}

# ---------------------------------------------------------------- 3. 빠른 시작/최대 절전 끄기
Step '3. 빠른 시작·최대 절전 끄기, 전원 설정'
if ($PSCmdlet.ShouldProcess('Power', 'HiberbootEnabled=0, hibernate off, standby 60m')) {
    Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power' -Name HiberbootEnabled -Value 0
    powercfg /hibernate off | Out-Null
    # 원격 사용 중 PC 가 잠들지 않도록: 전원 연결 시 절전 60분 (유휴 회수는 이후 에이전트가 담당)
    powercfg /change standby-timeout-ac 60 | Out-Null
    powercfg /change monitor-timeout-ac 10 | Out-Null
}

# ---------------------------------------------------------------- 4. NIC Wake-on-LAN
Step '4. 유선 랜카드 Wake-on-LAN 활성화'
$nics = Get-NetAdapter -Physical | Where-Object { $_.Status -eq 'Up' -and $_.MediaType -eq '802.3' }
if (-not $nics) { Write-Warning '연결된 유선 어댑터가 없습니다. WoL 은 유선 연결에서만 신뢰할 수 있습니다.' }
foreach ($nic in $nics) {
    if ($PSCmdlet.ShouldProcess($nic.Name, 'WakeOnMagicPacket Enabled')) {
        Set-NetAdapterPowerManagement -Name $nic.Name -WakeOnMagicPacket Enabled -ErrorAction SilentlyContinue
        # 제조사마다 고급 속성 키워드가 다르다. 없는 키워드는 무시.
        foreach ($kw in '*WakeOnMagicPacket', 'S5WakeOnLan', 'WakeFromS5', 'EnablePME') {
            Set-NetAdapterAdvancedProperty -Name $nic.Name -RegistryKeyword $kw -RegistryValue 1 -ErrorAction SilentlyContinue
        }
        # 절전 모드 랜카드 링크 끊김 방지(그린 이더넷 등)는 장치마다 달라 가이드에서 수동 확인
        powercfg /deviceenablewake "$($nic.InterfaceDescription)" 2>$null | Out-Null
    }
}

# ---------------------------------------------------------------- 5. RDP 에서 GPU 사용
Step '5. 원격 세션에서 하드웨어 GPU 사용 정책'
$pol = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services'
if ($PSCmdlet.ShouldProcess($pol, 'bEnumerateHWBeforeSW=1, AVC444ModePreferred=1, AVCHardwareEncodePreferred=1')) {
    New-Item -Path $pol -Force | Out-Null
    # "모든 원격 데스크톱 서비스 세션에 하드웨어 그래픽 어댑터 사용" — Revit 뷰포트가 소프트웨어 렌더링으로 떨어지는 것을 방지
    Set-ItemProperty -Path $pol -Name bEnumerateHWBeforeSW -Value 1 -Type DWord
    # H.264/AVC 444 및 하드웨어 인코딩 우선 (네이티브 RDP 클라이언트에서 효과. Guacamole 경유 시 효과는 제한적)
    Set-ItemProperty -Path $pol -Name AVC444ModePreferred -Value 1 -Type DWord
    Set-ItemProperty -Path $pol -Name AVCHardwareEncodePreferred -Value 1 -Type DWord
}

# ---------------------------------------------------------------- 6. 원격 접속 허용 사용자
if ($RemoteUsers.Count -gt 0) {
    Step '6. Remote Desktop Users 그룹에 계정 추가'
    foreach ($u in $RemoteUsers) {
        if ($PSCmdlet.ShouldProcess($u, 'Add to Remote Desktop Users (S-1-5-32-555)')) {
            try { Add-LocalGroupMember -SID 'S-1-5-32-555' -Member $u }
            catch { if ($_.Exception.Message -notmatch 'already|이미') { throw } }
        }
    }
}

# ---------------------------------------------------------------- 7. 등록 정보
Step '7. 등록 정보 수집'
$gpu = (Get-CimInstance Win32_VideoController | Where-Object { $_.Name -notmatch 'Basic|Remote|Virtual' } |
        Select-Object -ExpandProperty Name) -join ' / '
$sw = @()
foreach ($p in 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
               'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*') {
    $sw += Get-ItemProperty $p -ErrorAction SilentlyContinue |
           Where-Object { $_.DisplayName -match '^(Autodesk Revit|Revit|MIDAS|midas)' } |
           Select-Object -ExpandProperty DisplayName
}
$rows = foreach ($nic in $nics) {
    [pscustomobject]@{
        ComputerName = $env:COMPUTERNAME
        MAC          = $nic.MacAddress -replace '-', ':'
        IPv4         = (Get-NetIPAddress -InterfaceIndex $nic.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
                        Select-Object -First 1 -ExpandProperty IPAddress)
        NIC          = $nic.InterfaceDescription
        GPU          = $gpu
        Software     = ($sw | Sort-Object -Unique) -join '; '
        Collected    = (Get-Date -Format 's')
    }
}
$rows | Format-Table -AutoSize
if ($rows -and $PSCmdlet.ShouldProcess($OutputCsv, 'Append CSV')) {
    $rows | Export-Csv -Path $OutputCsv -NoTypeInformation -Append -Encoding UTF8
    Write-Host "저장: $OutputCsv"
}

Write-Host "`n완료. BIOS/UEFI WoL 설정을 확인한 뒤 '종료 -> 다른 PC 에서 wol.py' 로 깨우기 테스트를 하세요." -ForegroundColor Green
