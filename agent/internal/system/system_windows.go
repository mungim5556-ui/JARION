//go:build windows

package system

import (
	"fmt"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"sync"
	"time"
	"unsafe"

	"golang.org/x/sys/windows"
)

var (
	wtsapi32                        = windows.NewLazySystemDLL("wtsapi32.dll")
	kernel32                        = windows.NewLazySystemDLL("kernel32.dll")
	procWTSEnumerateSessionsW       = wtsapi32.NewProc("WTSEnumerateSessionsW")
	procWTSQuerySessionInformationW = wtsapi32.NewProc("WTSQuerySessionInformationW")
	procWTSFreeMemory               = wtsapi32.NewProc("WTSFreeMemory")
	procWTSLogoffSession            = wtsapi32.NewProc("WTSLogoffSession")
	procWTSSendMessageW             = wtsapi32.NewProc("WTSSendMessageW")
	procWTSGetActiveConsoleSession  = kernel32.NewProc("WTSGetActiveConsoleSessionId")
	procGetTickCount64              = kernel32.NewProc("GetTickCount64")
)

// WTS_CONNECTSTATE_CLASS
const (
	wtsActive       = 0
	wtsDisconnected = 4
)

// WTS_INFO_CLASS
const (
	wtsUserName           = 5
	wtsDomainName         = 7
	wtsClientName         = 10
	wtsClientProtocolType = 16
)

const (
	mbOK              = 0x0
	mbIconInformation = 0x40
	mbSetForeground   = 0x10000
	mbTopmost         = 0x40000
)

type wtsSessionInfo struct {
	SessionID      uint32
	WinStationName *uint16
	State          uint32
}

// Windows 는 실제 Windows 구현.
type Windows struct {
	mu sync.Mutex
	// 한 번이라도 RDP 로 연결된 것을 본 세션 ID. 연결이 끊기면 Windows 가 WinStation 이름을
	// 비워 버리므로, 끊긴 세션이 원격에서 온 것인지 이것으로 판단한다.
	seenRDP map[uint32]bool
}

func New() *Windows { return &Windows{seenRDP: map[uint32]bool{}} }

func (w *Windows) ComputerName() string {
	if n := os.Getenv("COMPUTERNAME"); n != "" {
		return n
	}
	n, _ := os.Hostname()
	return n
}

func (w *Windows) MACs() []string { return physicalMACs() }

func (w *Windows) Uptime() time.Duration {
	ms, _, _ := procGetTickCount64.Call()
	return time.Duration(ms) * time.Millisecond
}

func queryString(id uint32, class uint32) string {
	var buf *uint16
	var n uint32
	r, _, _ := procWTSQuerySessionInformationW.Call(0, uintptr(id), uintptr(class),
		uintptr(unsafe.Pointer(&buf)), uintptr(unsafe.Pointer(&n)))
	if r == 0 || buf == nil {
		return ""
	}
	defer procWTSFreeMemory.Call(uintptr(unsafe.Pointer(buf)))
	return windows.UTF16PtrToString(buf)
}

func queryProtocol(id uint32) uint16 {
	var buf *uint16
	var n uint32
	r, _, _ := procWTSQuerySessionInformationW.Call(0, uintptr(id), wtsClientProtocolType,
		uintptr(unsafe.Pointer(&buf)), uintptr(unsafe.Pointer(&n)))
	if r == 0 || buf == nil {
		return 0
	}
	defer procWTSFreeMemory.Call(uintptr(unsafe.Pointer(buf)))
	return *buf
}

func (w *Windows) Sessions() ([]Session, error) {
	var infos *wtsSessionInfo
	var count uint32
	r, _, err := procWTSEnumerateSessionsW.Call(0, 0, 1, uintptr(unsafe.Pointer(&infos)), uintptr(unsafe.Pointer(&count)))
	if r == 0 {
		return nil, fmt.Errorf("WTSEnumerateSessions: %w", err)
	}
	defer procWTSFreeMemory.Call(uintptr(unsafe.Pointer(infos)))
	list := unsafe.Slice(infos, count)

	consoleID, _, _ := procWTSGetActiveConsoleSession.Call()

	w.mu.Lock()
	defer w.mu.Unlock()
	alive := map[uint32]bool{}
	var out []Session
	for _, si := range list {
		if si.SessionID == 0 { // 서비스 세션
			continue
		}
		alive[si.SessionID] = true
		station := ""
		if si.WinStationName != nil {
			station = windows.UTF16PtrToString(si.WinStationName)
		}
		s := Session{
			ID:         si.SessionID,
			User:       queryString(si.SessionID, wtsUserName),
			Domain:     queryString(si.SessionID, wtsDomainName),
			ClientName: queryString(si.SessionID, wtsClientName),
		}
		switch si.State {
		case wtsActive:
			s.State = StateActive
		case wtsDisconnected:
			s.State = StateDisconnected
		default:
			s.State = StateOther
		}
		isRDP := strings.HasPrefix(strings.ToUpper(station), "RDP") || queryProtocol(si.SessionID) == 2
		switch {
		case isRDP:
			s.Protocol = ProtoRDP
			w.seenRDP[si.SessionID] = true
		case uint32(consoleID) == si.SessionID:
			s.Protocol = ProtoConsole
		case s.State == StateDisconnected && w.seenRDP[si.SessionID]:
			s.Protocol = ProtoRDP
		default:
			s.Protocol = ProtoOther
		}
		out = append(out, s)
	}
	for id := range w.seenRDP {
		if !alive[id] {
			delete(w.seenRDP, id)
		}
	}
	return out, nil
}

func (w *Windows) Processes() ([]string, error) {
	snap, err := windows.CreateToolhelp32Snapshot(windows.TH32CS_SNAPPROCESS, 0)
	if err != nil {
		return nil, err
	}
	defer windows.CloseHandle(snap)
	var e windows.ProcessEntry32
	e.Size = uint32(unsafe.Sizeof(e))
	var out []string
	for err = windows.Process32First(snap, &e); err == nil; err = windows.Process32Next(snap, &e) {
		out = append(out, windows.UTF16ToString(e.ExeFile[:]))
	}
	return out, nil
}

func (w *Windows) SendMessage(sessionID uint32, title, text string) error {
	t, _ := windows.UTF16FromString(title)
	m, _ := windows.UTF16FromString(text)
	var resp uint32
	r, _, err := procWTSSendMessageW.Call(0, uintptr(sessionID),
		uintptr(unsafe.Pointer(&t[0])), uintptr((len(t)-1)*2),
		uintptr(unsafe.Pointer(&m[0])), uintptr((len(m)-1)*2),
		mbOK|mbIconInformation|mbSetForeground|mbTopmost,
		0, uintptr(unsafe.Pointer(&resp)), 0) // bWait=FALSE: 띄우고 바로 반환
	if r == 0 {
		return fmt.Errorf("WTSSendMessage(%d): %w", sessionID, err)
	}
	return nil
}

func (w *Windows) Logoff(sessionID uint32) error {
	r, _, err := procWTSLogoffSession.Call(0, uintptr(sessionID), 0)
	if r == 0 {
		return fmt.Errorf("WTSLogoffSession(%d): %w", sessionID, err)
	}
	return nil
}

func (w *Windows) Shutdown(delay time.Duration, message string) error {
	secs := int(delay.Seconds())
	if secs < 0 {
		secs = 0
	}
	out, err := exec.Command("shutdown.exe", "/s", "/t", strconv.Itoa(secs), "/c", message, "/d", "p:0:0").CombinedOutput()
	if err != nil {
		return fmt.Errorf("shutdown.exe: %v: %s", err, strings.TrimSpace(string(out)))
	}
	return nil
}
