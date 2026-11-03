// Package client 는 포털 API(/api/agent/*) 호출을 담당한다.
package client

import (
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"time"

	"github.com/mungim5556-ui/jarion/agent/internal/system"
)

// ErrUnauthorized 는 토큰이 폐기되었거나 다시 등록해야 할 때.
var ErrUnauthorized = errors.New("unauthorized")

type Client struct {
	base string
	http *http.Client
}

func New(baseURL, caFile string) (*Client, error) {
	tlsCfg := &tls.Config{MinVersion: tls.VersionTLS12}
	if caFile != "" {
		pem, err := os.ReadFile(caFile)
		if err != nil {
			return nil, fmt.Errorf("ca_file: %w", err)
		}
		pool, err := x509.SystemCertPool()
		if err != nil || pool == nil {
			pool = x509.NewCertPool()
		}
		if !pool.AppendCertsFromPEM(pem) {
			return nil, fmt.Errorf("ca_file 에서 인증서를 읽지 못했습니다: %s", caFile)
		}
		tlsCfg.RootCAs = pool
	}
	tr := http.DefaultTransport.(*http.Transport).Clone()
	tr.TLSClientConfig = tlsCfg
	return &Client{base: baseURL, http: &http.Client{Timeout: 20 * time.Second, Transport: tr}}, nil
}

type EnrollRequest struct {
	EnrollmentKey string   `json:"enrollment_key"`
	ComputerName  string   `json:"computer_name"`
	MACs          []string `json:"macs"`
	Version       string   `json:"version"`
}

type EnrollResponse struct {
	Token           string `json:"token"`
	MachineName     string `json:"machine_name"`
	IntervalSeconds int    `json:"interval_seconds"`
}

type Result struct {
	ID    int64  `json:"id"`
	OK    bool   `json:"ok"`
	Error string `json:"error"`
}

type HeartbeatRequest struct {
	Version       string           `json:"version"`
	UptimeSeconds int64            `json:"uptime_seconds"`
	Sessions      []system.Session `json:"sessions"`
	Processes     []string         `json:"processes"`
	Results       []Result         `json:"results"`
}

type Command struct {
	ID      int64           `json:"id"`
	Kind    string          `json:"kind"`
	Payload json.RawMessage `json:"payload"`
}

type HeartbeatResponse struct {
	MachineName     string    `json:"machine_name"`
	IntervalSeconds int       `json:"interval_seconds"`
	WatchProcesses  []string  `json:"watch_processes"`
	ExemptUsers     []string  `json:"exempt_users"`
	Commands        []Command `json:"commands"`
}

func (c *Client) post(ctx context.Context, path, token string, in, out any) error {
	body, err := json.Marshal(in)
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.base+path, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("User-Agent", "jarion-agent")
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if resp.StatusCode == http.StatusUnauthorized {
		return ErrUnauthorized
	}
	if resp.StatusCode/100 != 2 {
		var e struct {
			Detail any `json:"detail"`
		}
		_ = json.Unmarshal(data, &e)
		return fmt.Errorf("%s: HTTP %d: %v", path, resp.StatusCode, e.Detail)
	}
	return json.Unmarshal(data, out)
}

func (c *Client) Enroll(ctx context.Context, r EnrollRequest) (*EnrollResponse, error) {
	var out EnrollResponse
	return &out, c.post(ctx, "/api/agent/enroll", "", r, &out)
}

func (c *Client) Heartbeat(ctx context.Context, token string, r HeartbeatRequest) (*HeartbeatResponse, error) {
	var out HeartbeatResponse
	return &out, c.post(ctx, "/api/agent/heartbeat", token, r, &out)
}
