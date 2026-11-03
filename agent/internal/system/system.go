// Package system 은 에이전트가 PC 에서 하는 일(세션 조회, 로그오프, 메시지, 종료)을
// 운영체제와 분리한 인터페이스로 정의한다. Windows 구현은 system_windows.go.
package system

import "time"

// 세션 상태
const (
	StateActive       = "active"
	StateDisconnected = "disconnected"
	StateOther        = "other"
)

// 세션 종류
const (
	ProtoConsole = "console" // PC 앞에 앉아 로그인한 사람
	ProtoRDP     = "rdp"     // 원격 데스크톱
	ProtoOther   = "other"   // 판단 불가 (예: 빠른 사용자 전환으로 끊긴 로컬 세션)
)

// Session 은 Windows 로그온 세션 하나.
type Session struct {
	ID         uint32 `json:"id"`
	User       string `json:"user"`
	Domain     string `json:"domain"`
	State      string `json:"state"`
	Protocol   string `json:"protocol"`
	ClientName string `json:"client_name"`
}

// System 은 에이전트가 쓰는 운영체제 기능.
type System interface {
	ComputerName() string
	MACs() []string
	Uptime() time.Duration
	Sessions() ([]Session, error)
	Processes() ([]string, error)
	SendMessage(sessionID uint32, title, text string) error
	Logoff(sessionID uint32) error
	Shutdown(delay time.Duration, message string) error
}
