// Package agent 는 에이전트 본체: 포털에 주기적으로 PC 상태를 보고하고, 받은 명령을 실행한다.
//
// 안전 원칙
//   - 로그오프·안내 메시지는 원격(RDP) 세션에만 한다. PC 앞에 앉은 사람(콘솔)은 절대 건드리지 않는다.
//   - 제외 계정(IT 관리자 등)은 로그오프하지 않는다.
//   - 종료(shutdown)는 로그인한 사람이 한 명이라도 있으면 거부한다.
package agent

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"path"
	"strings"
	"time"

	"github.com/mungim5556-ui/jarion/agent/internal/client"
	"github.com/mungim5556-ui/jarion/agent/internal/config"
	"github.com/mungim5556-ui/jarion/agent/internal/system"
)

var Version = "0.1.0"

type API interface {
	Enroll(ctx context.Context, r client.EnrollRequest) (*client.EnrollResponse, error)
	Heartbeat(ctx context.Context, token string, r client.HeartbeatRequest) (*client.HeartbeatResponse, error)
}

type Agent struct {
	Cfg    *config.Config
	Sys    system.System
	API    API
	Tokens config.TokenStore
	Log    *log.Logger

	token    string
	interval time.Duration
	watch    []string
	exempt   map[string]bool
	results  []client.Result
}

func New(cfg *config.Config, sys system.System, api API, tokens config.TokenStore, logger *log.Logger) *Agent {
	return &Agent{Cfg: cfg, Sys: sys, API: api, Tokens: tokens, Log: logger,
		interval: 15 * time.Second, exempt: map[string]bool{}}
}

func (a *Agent) Interval() time.Duration { return a.interval }

// Run 은 ctx 가 취소될 때까지 보고/명령 실행을 반복한다.
func (a *Agent) Run(ctx context.Context) {
	a.Log.Printf("jarion-agent %s 시작 (%s, %s)", Version, a.Sys.ComputerName(), a.Cfg.APIURL)
	backoff := 0
	for {
		err := a.Step(ctx)
		wait := a.interval // 서버가 알려준 주기를 바로 반영
		if err != nil {
			backoff = min(backoff+1, 6)
			wait = time.Duration(1<<backoff) * 5 * time.Second // 10s ~ 5m20s
			a.Log.Printf("오류: %v (%s 후 재시도)", err, wait)
		} else {
			backoff = 0
		}
		select {
		case <-ctx.Done():
			a.Log.Printf("종료")
			return
		case <-time.After(wait):
		}
	}
}

// Step 은 한 번의 보고 주기: (필요하면 등록) -> 상태 보고 -> 받은 명령 실행.
func (a *Agent) Step(ctx context.Context) error {
	if a.token == "" {
		a.token = a.Tokens.Load()
	}
	if a.token == "" {
		if err := a.enroll(ctx); err != nil {
			return fmt.Errorf("등록 실패: %w", err)
		}
	}

	sessions, err := a.Sys.Sessions()
	if err != nil {
		return err
	}
	req := client.HeartbeatRequest{
		Version:       Version,
		UptimeSeconds: int64(a.Sys.Uptime().Seconds()),
		Sessions:      sessions,
		Processes:     a.watchedProcesses(),
		Results:       a.results,
	}
	if req.Sessions == nil {
		req.Sessions = []system.Session{}
	}
	if req.Results == nil {
		req.Results = []client.Result{}
	}

	resp, err := a.API.Heartbeat(ctx, a.token, req)
	if errors.Is(err, client.ErrUnauthorized) {
		a.Log.Printf("토큰이 거부되었습니다. 다시 등록합니다")
		a.token = ""
		a.Tokens.Clear()
		return err
	}
	if err != nil {
		return err
	}
	a.results = nil
	a.apply(resp)

	for _, cmd := range resp.Commands {
		res := client.Result{ID: cmd.ID, OK: true}
		if err := a.execute(cmd, sessions); err != nil {
			res.OK, res.Error = false, err.Error()
			a.Log.Printf("명령 #%d %s 실패: %v", cmd.ID, cmd.Kind, err)
		} else {
			a.Log.Printf("명령 #%d %s 완료", cmd.ID, cmd.Kind)
		}
		a.results = append(a.results, res)
	}
	return nil
}

func (a *Agent) enroll(ctx context.Context) error {
	r, err := a.API.Enroll(ctx, client.EnrollRequest{
		EnrollmentKey: a.Cfg.EnrollmentKey,
		ComputerName:  a.Sys.ComputerName(),
		MACs:          a.Sys.MACs(),
		Version:       Version,
	})
	if err != nil {
		return err
	}
	if err := a.Tokens.Save(r.Token); err != nil {
		return fmt.Errorf("토큰 저장: %w", err)
	}
	a.token = r.Token
	if r.IntervalSeconds > 0 {
		a.interval = time.Duration(r.IntervalSeconds) * time.Second
	}
	a.Log.Printf("포털에 %s 로 등록되었습니다", r.MachineName)
	return nil
}

func (a *Agent) apply(r *client.HeartbeatResponse) {
	if r.IntervalSeconds >= 5 {
		a.interval = time.Duration(r.IntervalSeconds) * time.Second
	}
	a.watch = a.watch[:0]
	for _, p := range r.WatchProcesses {
		a.watch = append(a.watch, strings.ToLower(p))
	}
	a.exempt = map[string]bool{}
	for _, u := range r.ExemptUsers {
		a.exempt[strings.ToLower(u)] = true
	}
}

func (a *Agent) watchedProcesses() []string {
	out := []string{}
	if len(a.watch) == 0 {
		return out
	}
	procs, err := a.Sys.Processes()
	if err != nil {
		a.Log.Printf("프로세스 목록 실패: %v", err)
		return out
	}
	seen := map[string]bool{}
	for _, p := range procs {
		lp := strings.ToLower(p)
		for _, pat := range a.watch {
			if ok, _ := path.Match(pat, lp); ok && !seen[lp] {
				seen[lp] = true
				out = append(out, p)
			}
		}
	}
	return out
}

func (a *Agent) isExempt(s system.Session) bool {
	u := strings.ToLower(s.User)
	return a.exempt[u] || a.exempt[strings.ToLower(s.Domain)+`\`+u]
}

// remoteTargets 는 명령 대상이 되는 원격 세션 (로그인한 사용자가 있고, 제외 계정이 아닌 RDP 세션).
func (a *Agent) remoteTargets(sessions []system.Session) []system.Session {
	var out []system.Session
	for _, s := range sessions {
		if s.Protocol == system.ProtoRDP && s.User != "" && !a.isExempt(s) {
			out = append(out, s)
		}
	}
	return out
}

func (a *Agent) execute(cmd client.Command, sessions []system.Session) error {
	switch cmd.Kind {
	case "message":
		var p struct{ Title, Text string }
		if err := json.Unmarshal(cmd.Payload, &p); err != nil {
			return err
		}
		var errs []error
		for _, s := range a.remoteTargets(sessions) {
			if s.State != system.StateActive { // 끊긴 세션에는 보여줄 화면이 없다
				continue
			}
			if err := a.Sys.SendMessage(s.ID, p.Title, p.Text); err != nil {
				errs = append(errs, err)
			}
		}
		return errors.Join(errs...)

	case "logoff":
		var errs []error
		for _, s := range a.remoteTargets(sessions) {
			a.Log.Printf("원격 세션 로그오프: #%d %s\\%s", s.ID, s.Domain, s.User)
			if err := a.Sys.Logoff(s.ID); err != nil {
				errs = append(errs, err)
			}
		}
		return errors.Join(errs...)

	case "shutdown":
		var p struct {
			DelaySeconds int    `json:"delay_seconds"`
			Message      string `json:"message"`
		}
		if err := json.Unmarshal(cmd.Payload, &p); err != nil {
			return err
		}
		for _, s := range sessions {
			if s.User != "" {
				return fmt.Errorf("로그인한 사용자(%s)가 있어 종료하지 않습니다", s.User)
			}
		}
		return a.Sys.Shutdown(time.Duration(p.DelaySeconds)*time.Second, p.Message)

	default:
		return fmt.Errorf("알 수 없는 명령: %s", cmd.Kind)
	}
}
