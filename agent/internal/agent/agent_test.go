package agent

import (
	"context"
	"encoding/json"
	"io"
	"log"
	"path/filepath"
	"testing"
	"time"

	"github.com/mungim5556-ui/jarion/agent/internal/client"
	"github.com/mungim5556-ui/jarion/agent/internal/config"
	"github.com/mungim5556-ui/jarion/agent/internal/system"
)

// ---------- 가짜 PC
type fakeSys struct {
	sessions  []system.Session
	procs     []string
	loggedOff []uint32
	messages  []uint32
	shutdowns int
}

func (f *fakeSys) ComputerName() string                 { return "LAB-PC01" }
func (f *fakeSys) MACs() []string                       { return []string{"AA:BB:CC:DD:EE:01"} }
func (f *fakeSys) Uptime() time.Duration                { return time.Hour }
func (f *fakeSys) Sessions() ([]system.Session, error)  { return f.sessions, nil }
func (f *fakeSys) Processes() ([]string, error)         { return f.procs, nil }
func (f *fakeSys) Logoff(id uint32) error               { f.loggedOff = append(f.loggedOff, id); return nil }
func (f *fakeSys) Shutdown(time.Duration, string) error { f.shutdowns++; return nil }
func (f *fakeSys) SendMessage(id uint32, _, _ string) error {
	f.messages = append(f.messages, id)
	return nil
}

// ---------- 가짜 포털
type fakeAPI struct {
	enrolls int
	token   string
	reject  bool
	queue   []client.Command
	last    client.HeartbeatRequest
	exempt  []string
	watch   []string
}

func (f *fakeAPI) Enroll(_ context.Context, r client.EnrollRequest) (*client.EnrollResponse, error) {
	f.enrolls++
	f.token = "tok-" + r.ComputerName
	f.reject = false
	return &client.EnrollResponse{Token: f.token, MachineName: r.ComputerName, IntervalSeconds: 15}, nil
}

func (f *fakeAPI) Heartbeat(_ context.Context, token string, r client.HeartbeatRequest) (*client.HeartbeatResponse, error) {
	if f.reject || token != f.token {
		return nil, client.ErrUnauthorized
	}
	f.last = r
	cmds := f.queue
	f.queue = nil
	return &client.HeartbeatResponse{IntervalSeconds: 15, Commands: cmds, ExemptUsers: f.exempt, WatchProcesses: f.watch}, nil
}

func newAgent(t *testing.T, sys *fakeSys, api *fakeAPI) *Agent {
	t.Helper()
	cfg := &config.Config{APIURL: "https://portal.test", EnrollmentKey: "k"}
	store := config.TokenStore{Path: filepath.Join(t.TempDir(), "token")}
	return New(cfg, sys, api, store, log.New(io.Discard, "", 0))
}

func cmd(id int64, kind string, payload any) client.Command {
	b, _ := json.Marshal(payload)
	return client.Command{ID: id, Kind: kind, Payload: b}
}

var (
	consoleKim = system.Session{ID: 1, User: "kim", Domain: "SCHOOL", State: system.StateActive, Protocol: system.ProtoConsole}
	rdpLee     = system.Session{ID: 2, User: "lee", Domain: "SCHOOL", State: system.StateActive, Protocol: system.ProtoRDP}
	rdpAdmin   = system.Session{ID: 3, User: "itadmin", Domain: "SCHOOL", State: system.StateActive, Protocol: system.ProtoRDP}
	rdpGone    = system.Session{ID: 4, User: "park", Domain: "SCHOOL", State: system.StateDisconnected, Protocol: system.ProtoRDP}
	loginScr   = system.Session{ID: 5, User: "", State: system.StateActive, Protocol: system.ProtoRDP}
)

func TestEnrollsOnceAndPersistsToken(t *testing.T) {
	sys, api := &fakeSys{}, &fakeAPI{}
	a := newAgent(t, sys, api)
	ctx := context.Background()
	for i := 0; i < 3; i++ {
		if err := a.Step(ctx); err != nil {
			t.Fatal(err)
		}
	}
	if api.enrolls != 1 {
		t.Fatalf("enrolls = %d, want 1", api.enrolls)
	}
	if got := a.Tokens.Load(); got != "tok-LAB-PC01" {
		t.Fatalf("token file = %q", got)
	}

	// 재시작해도 저장된 토큰을 써서 다시 등록하지 않음
	b := New(a.Cfg, sys, api, a.Tokens, a.Log)
	if err := b.Step(ctx); err != nil {
		t.Fatal(err)
	}
	if api.enrolls != 1 {
		t.Fatalf("re-enrolled after restart")
	}
}

func TestReenrollAfterTokenRevoked(t *testing.T) {
	sys, api := &fakeSys{}, &fakeAPI{}
	a := newAgent(t, sys, api)
	ctx := context.Background()
	_ = a.Step(ctx)
	api.reject = true
	if err := a.Step(ctx); err == nil {
		t.Fatal("expected unauthorized")
	}
	if a.Tokens.Load() != "" {
		t.Fatal("token not cleared")
	}
	if err := a.Step(ctx); err != nil {
		t.Fatal(err)
	}
	if api.enrolls != 2 {
		t.Fatalf("enrolls = %d, want 2", api.enrolls)
	}
}

func TestLogoffOnlyRemoteAndNotExempt(t *testing.T) {
	sys := &fakeSys{sessions: []system.Session{consoleKim, rdpLee, rdpAdmin, rdpGone, loginScr}}
	api := &fakeAPI{exempt: []string{"itadmin"}}
	a := newAgent(t, sys, api)
	ctx := context.Background()
	_ = a.Step(ctx) // 제외 계정 목록을 받음
	api.queue = []client.Command{cmd(7, "logoff", map[string]string{"target": "remote"})}
	if err := a.Step(ctx); err != nil {
		t.Fatal(err)
	}
	// 콘솔(kim)·제외 계정(itadmin)·로그인 전 화면은 제외, lee 와 끊긴 park 만
	if len(sys.loggedOff) != 2 || sys.loggedOff[0] != 2 || sys.loggedOff[1] != 4 {
		t.Fatalf("loggedOff = %v, want [2 4]", sys.loggedOff)
	}
	// 결과는 다음 보고 때 전달
	_ = a.Step(ctx)
	if len(api.last.Results) != 1 || api.last.Results[0].ID != 7 || !api.last.Results[0].OK {
		t.Fatalf("results = %+v", api.last.Results)
	}
	_ = a.Step(ctx)
	if len(api.last.Results) != 0 {
		t.Fatal("results reported twice")
	}
}

func TestMessageOnlyToActiveRemote(t *testing.T) {
	sys := &fakeSys{sessions: []system.Session{consoleKim, rdpLee, rdpGone}}
	api := &fakeAPI{}
	a := newAgent(t, sys, api)
	api.queue = []client.Command{cmd(1, "message", map[string]string{"title": "t", "text": "10분 남음"})}
	_ = a.Step(context.Background())
	if len(sys.messages) != 1 || sys.messages[0] != 2 {
		t.Fatalf("messages = %v, want [2]", sys.messages)
	}
}

func TestShutdownRefusedWhenSomeoneLoggedIn(t *testing.T) {
	sys := &fakeSys{sessions: []system.Session{consoleKim}}
	api := &fakeAPI{}
	a := newAgent(t, sys, api)
	ctx := context.Background()
	api.queue = []client.Command{cmd(9, "shutdown", map[string]any{"delay_seconds": 60})}
	_ = a.Step(ctx)
	if sys.shutdowns != 0 {
		t.Fatal("shut down with user logged in")
	}
	_ = a.Step(ctx)
	if r := api.last.Results; len(r) != 1 || r[0].OK {
		t.Fatalf("expected failed result, got %+v", r)
	}

	sys.sessions = []system.Session{loginScr}
	api.queue = []client.Command{cmd(10, "shutdown", map[string]any{"delay_seconds": 60})}
	_ = a.Step(ctx)
	if sys.shutdowns != 1 {
		t.Fatal("expected shutdown when nobody logged in")
	}
}

func TestWatchedProcesses(t *testing.T) {
	sys := &fakeSys{procs: []string{"explorer.exe", "Revit.exe", "midas_civil.exe", "midas_civil.exe", "chrome.exe"}}
	api := &fakeAPI{watch: []string{"Revit.exe", "midas*.exe"}}
	a := newAgent(t, sys, api)
	ctx := context.Background()
	_ = a.Step(ctx) // 감시 목록 수신
	_ = a.Step(ctx)
	got := api.last.Processes
	if len(got) != 2 || got[0] != "Revit.exe" || got[1] != "midas_civil.exe" {
		t.Fatalf("processes = %v", got)
	}
}

func TestUnknownCommandReportsError(t *testing.T) {
	sys, api := &fakeSys{}, &fakeAPI{}
	a := newAgent(t, sys, api)
	ctx := context.Background()
	api.queue = []client.Command{cmd(3, "format_c", nil)}
	_ = a.Step(ctx)
	_ = a.Step(ctx)
	if r := api.last.Results; len(r) != 1 || r[0].OK {
		t.Fatalf("results = %+v", r)
	}
}
