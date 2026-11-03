//go:build !windows

package system

import (
	"errors"
	"os"
	"time"
)

// Stub 은 Windows 가 아닌 곳에서 개발·테스트용으로 실행할 때 쓰는 구현.
// 세션이 하나도 없는 PC 처럼 동작하고, 명령은 실행하지 않는다.
type Stub struct{ start time.Time }

func New() *Stub { return &Stub{start: time.Now()} }

var errUnsupported = errors.New("이 운영체제에서는 지원하지 않습니다 (Windows 전용)")

func (s *Stub) ComputerName() string {
	if n := os.Getenv("COMPUTERNAME"); n != "" {
		return n
	}
	n, _ := os.Hostname()
	return n
}
func (s *Stub) MACs() []string                           { return physicalMACs() }
func (s *Stub) Uptime() time.Duration                    { return time.Since(s.start) }
func (s *Stub) Sessions() ([]Session, error)             { return nil, nil }
func (s *Stub) Processes() ([]string, error)             { return nil, nil }
func (s *Stub) SendMessage(uint32, string, string) error { return errUnsupported }
func (s *Stub) Logoff(uint32) error                      { return errUnsupported }
func (s *Stub) Shutdown(time.Duration, string) error     { return errUnsupported }
