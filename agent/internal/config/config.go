// Package config 는 에이전트 설정 파일과 발급받은 토큰 파일을 다룬다.
//
// Windows 기본 위치: C:\ProgramData\JARION\agent.json, C:\ProgramData\JARION\token
// (설치 시 이 폴더는 SYSTEM 과 Administrators 만 읽을 수 있게 권한을 바꾼다)
package config

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"strings"
)

type Config struct {
	APIURL        string `json:"api_url"`           // 예: https://remote.school.ac.kr
	EnrollmentKey string `json:"enrollment_key"`    // 포털의 JARION_AGENT_ENROLLMENT_KEY
	CAFile        string `json:"ca_file,omitempty"` // 자체 서명 인증서를 쓸 때 PEM 경로
}

func DefaultDir() string {
	if d := os.Getenv("JARION_AGENT_DIR"); d != "" { // 테스트·문제 확인용
		return d
	}
	if runtime.GOOS == "windows" {
		if pd := os.Getenv("ProgramData"); pd != "" {
			return filepath.Join(pd, "JARION")
		}
		return `C:\ProgramData\JARION`
	}
	return "/etc/jarion-agent"
}

func ConfigPath(dir string) string { return filepath.Join(dir, "agent.json") }
func TokenPath(dir string) string  { return filepath.Join(dir, "token") }
func LogPath(dir string) string    { return filepath.Join(dir, "agent.log") }

func (c *Config) Validate() error {
	u, err := url.Parse(c.APIURL)
	if err != nil || u.Host == "" || (u.Scheme != "https" && u.Scheme != "http") {
		return fmt.Errorf("api_url 이 올바르지 않습니다: %q", c.APIURL)
	}
	if c.EnrollmentKey == "" {
		return errors.New("enrollment_key 가 비어 있습니다")
	}
	c.APIURL = strings.TrimRight(c.APIURL, "/")
	return nil
}

func Load(path string) (*Config, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var c Config
	if err := json.Unmarshal(b, &c); err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	return &c, c.Validate()
}

func Save(path string, c *Config) error {
	b, err := json.MarshalIndent(c, "", "  ")
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	return os.WriteFile(path, b, 0o600)
}

// TokenStore 는 포털이 발급한 PC 전용 토큰을 파일에 보관한다.
type TokenStore struct{ Path string }

func (t TokenStore) Load() string {
	b, err := os.ReadFile(t.Path)
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(b))
}

func (t TokenStore) Save(token string) error {
	if err := os.MkdirAll(filepath.Dir(t.Path), 0o700); err != nil {
		return err
	}
	return os.WriteFile(t.Path, []byte(token), 0o600)
}

func (t TokenStore) Clear() { _ = os.Remove(t.Path) }
