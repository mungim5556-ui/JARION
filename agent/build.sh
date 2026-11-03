#!/usr/bin/env bash
# Windows 용 jarion-agent.exe 빌드 (Linux/macOS 에서 교차 컴파일 가능)
#   ./build.sh            -> dist/jarion-agent.exe (버전 0.1.0)
#   VERSION=0.2.0 ./build.sh
set -euo pipefail
cd "$(dirname "$0")"
VERSION="${VERSION:-0.1.0}"
mkdir -p dist
GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build -trimpath \
  -ldflags "-s -w -X github.com/mungim5556-ui/jarion/agent/internal/agent.Version=${VERSION}" \
  -o dist/jarion-agent.exe ./cmd/jarion-agent
sha256sum dist/jarion-agent.exe
