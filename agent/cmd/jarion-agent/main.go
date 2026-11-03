// jarion-agent: JARION 원격 실습실 PC 에이전트.
//
//	jarion-agent install --api https://remote.school.ac.kr --key <등록키> [--ca server.pem]
//	jarion-agent uninstall
//	jarion-agent run          # 콘솔에서 실행 (문제 확인용)
//	jarion-agent sessions     # 에이전트가 보는 로그온 세션 출력 (문제 확인용)
//	jarion-agent version
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"os"
	"os/signal"
	"path/filepath"

	"github.com/mungim5556-ui/jarion/agent/internal/agent"
	"github.com/mungim5556-ui/jarion/agent/internal/client"
	"github.com/mungim5556-ui/jarion/agent/internal/config"
	"github.com/mungim5556-ui/jarion/agent/internal/service"
	"github.com/mungim5556-ui/jarion/agent/internal/system"
)

const maxLogBytes = 5 << 20

func main() {
	dir := config.DefaultDir()
	if service.IsService() {
		if err := service.RunService(func(ctx context.Context) { runAgent(ctx, dir, false) }); err != nil {
			os.Exit(1)
		}
		return
	}

	if len(os.Args) < 2 {
		usage()
		os.Exit(2)
	}
	switch os.Args[1] {
	case "install":
		fs := flag.NewFlagSet("install", flag.ExitOnError)
		api := fs.String("api", "", "포털 주소 (예: https://remote.school.ac.kr)")
		key := fs.String("key", "", "에이전트 등록 키 (포털의 JARION_AGENT_ENROLLMENT_KEY)")
		ca := fs.String("ca", "", "자체 서명 인증서를 쓸 때 서버 인증서(PEM) 경로")
		_ = fs.Parse(os.Args[2:])
		cfg := &config.Config{APIURL: *api, EnrollmentKey: *key}
		if *ca != "" {
			// 인증서는 데이터 폴더로 복사해 둔다 (원본 위치가 사라져도 동작하도록)
			b, err := os.ReadFile(*ca)
			fatalIf(err)
			cfg.CAFile = filepath.Join(dir, "server-ca.pem")
			fatalIf(os.MkdirAll(dir, 0o700))
			fatalIf(os.WriteFile(cfg.CAFile, b, 0o600))
		}
		fatalIf(cfg.Validate())
		fatalIf(config.Save(config.ConfigPath(dir), cfg))
		config.TokenStore{Path: config.TokenPath(dir)}.Clear() // 새로 등록
		fatalIf(service.Install(dir))
		fmt.Printf("설치 완료. 설정: %s, 로그: %s\n", config.ConfigPath(dir), config.LogPath(dir))

	case "uninstall":
		fatalIf(service.Uninstall())
		fmt.Println("서비스를 삭제했습니다. 설정 폴더는 남겨 두었습니다:", dir)

	case "run":
		ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
		defer stop()
		runAgent(ctx, dir, true)

	case "sessions":
		s, err := system.New().Sessions()
		fatalIf(err)
		enc := json.NewEncoder(os.Stdout)
		enc.SetIndent("", "  ")
		_ = enc.Encode(s)

	case "version":
		fmt.Println(agent.Version)

	default:
		usage()
		os.Exit(2)
	}
}

func runAgent(ctx context.Context, dir string, console bool) {
	logger := openLog(dir, console)
	cfg, err := config.Load(config.ConfigPath(dir))
	if err != nil {
		logger.Printf("설정을 읽지 못했습니다: %v", err)
		<-ctx.Done()
		return
	}
	api, err := client.New(cfg.APIURL, cfg.CAFile)
	if err != nil {
		logger.Printf("%v", err)
		<-ctx.Done()
		return
	}
	a := agent.New(cfg, system.New(), api, config.TokenStore{Path: config.TokenPath(dir)}, logger)
	a.Run(ctx)
}

// openLog 는 데이터 폴더의 agent.log 에 기록한다. 5MB 를 넘으면 .old 로 돌린다.
func openLog(dir string, console bool) *log.Logger {
	path := config.LogPath(dir)
	if st, err := os.Stat(path); err == nil && st.Size() > maxLogBytes {
		_ = os.Rename(path, path+".old")
	}
	_ = os.MkdirAll(dir, 0o700)
	var w io.Writer = io.Discard
	if f, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600); err == nil {
		w = f
	}
	if console {
		w = io.MultiWriter(w, os.Stderr)
	}
	return log.New(w, "", log.LstdFlags)
}

func fatalIf(err error) {
	if err != nil {
		fmt.Fprintln(os.Stderr, "오류:", err)
		os.Exit(1)
	}
}

func usage() {
	fmt.Fprintln(os.Stderr, `사용법:
  jarion-agent install --api <포털 주소> --key <등록 키> [--ca <서버 인증서.pem>]
  jarion-agent uninstall
  jarion-agent run        (콘솔에서 실행, 문제 확인용)
  jarion-agent sessions   (로그온 세션 확인)
  jarion-agent version`)
}
