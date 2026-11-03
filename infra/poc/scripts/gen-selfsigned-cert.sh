#!/usr/bin/env bash
# PoC 용 자체 서명 인증서 생성. 운영 시에는 학교 도메인 인증서(또는 Let's Encrypt)로 교체.
# 사용: ./scripts/gen-selfsigned-cert.sh remote.example.ac.kr
set -euo pipefail

cd "$(dirname "$0")/.."
CN="${1:-localhost}"

mkdir -p certs
openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
  -keyout certs/server.key -out certs/server.crt \
  -subj "/CN=${CN}" -addext "subjectAltName=DNS:${CN}"
chmod 600 certs/server.key
echo "생성됨: certs/server.crt, certs/server.key (CN=${CN})"
