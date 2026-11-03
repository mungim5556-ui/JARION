//go:build windows

// Package service 는 Windows 서비스 등록/해제와 서비스 실행을 담당한다.
package service

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"time"

	"golang.org/x/sys/windows/svc"
	"golang.org/x/sys/windows/svc/mgr"
)

const (
	Name        = "JarionAgent"
	DisplayName = "JARION 원격 실습실 에이전트"
	Description = "실습실 PC 상태를 JARION 포털에 보고하고, 원격 사용 종료 시 로그오프 등을 처리합니다."
)

// IsService 는 서비스 제어 관리자(SCM)가 실행했는지.
func IsService() bool {
	ok, err := svc.IsWindowsService()
	return err == nil && ok
}

type handler struct{ run func(ctx context.Context) }

func (h handler) Execute(_ []string, req <-chan svc.ChangeRequest, status chan<- svc.Status) (bool, uint32) {
	status <- svc.Status{State: svc.StartPending}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan struct{})
	go func() { h.run(ctx); close(done) }()
	status <- svc.Status{State: svc.Running, Accepts: svc.AcceptStop | svc.AcceptShutdown}
	for {
		select {
		case c := <-req:
			switch c.Cmd {
			case svc.Interrogate:
				status <- c.CurrentStatus
			case svc.Stop, svc.Shutdown:
				status <- svc.Status{State: svc.StopPending}
				cancel()
				select {
				case <-done:
				case <-time.After(10 * time.Second):
				}
				return false, 0
			}
		case <-done:
			return false, 0
		}
	}
}

// RunService 는 SCM 아래에서 에이전트를 실행한다.
func RunService(run func(ctx context.Context)) error {
	return svc.Run(Name, handler{run: run})
}

// Install 은 현재 실행 파일을 자동 시작 서비스로 등록하고 시작한다. 실패 시 자동 재시작하도록 설정.
func Install(dataDir string) error {
	exe, err := os.Executable()
	if err != nil {
		return err
	}
	// 설정/토큰 폴더: SYSTEM 과 Administrators 만 접근 (등록 키·토큰 보호)
	if out, err := exec.Command("icacls", dataDir, "/inheritance:r",
		"/grant:r", "*S-1-5-18:(OI)(CI)F", "/grant:r", "*S-1-5-32-544:(OI)(CI)F").CombinedOutput(); err != nil {
		return fmt.Errorf("icacls: %v: %s", err, out)
	}

	m, err := mgr.Connect()
	if err != nil {
		return err
	}
	defer m.Disconnect()

	if s, err := m.OpenService(Name); err == nil {
		s.Close()
		return fmt.Errorf("서비스 %s 가 이미 있습니다. 먼저 uninstall 하세요", Name)
	}
	s, err := m.CreateService(Name, exe, mgr.Config{
		DisplayName:      DisplayName,
		Description:      Description,
		StartType:        mgr.StartAutomatic,
		DelayedAutoStart: false,
	}, "service")
	if err != nil {
		return err
	}
	defer s.Close()
	_ = s.SetRecoveryActions([]mgr.RecoveryAction{
		{Type: mgr.ServiceRestart, Delay: 10 * time.Second},
		{Type: mgr.ServiceRestart, Delay: 30 * time.Second},
		{Type: mgr.ServiceRestart, Delay: 60 * time.Second},
	}, 24*60*60)
	return s.Start()
}

// Uninstall 은 서비스를 멈추고 삭제한다.
func Uninstall() error {
	m, err := mgr.Connect()
	if err != nil {
		return err
	}
	defer m.Disconnect()
	s, err := m.OpenService(Name)
	if err != nil {
		return fmt.Errorf("서비스 %s 가 없습니다", Name)
	}
	defer s.Close()
	_, _ = s.Control(svc.Stop)
	for i := 0; i < 20; i++ {
		st, err := s.Query()
		if err != nil || st.State == svc.Stopped {
			break
		}
		time.Sleep(500 * time.Millisecond)
	}
	return s.Delete()
}
