#!/usr/bin/env bash
# Guacamole PostgreSQL 스키마(initdb.sql)를 공식 이미지에서 추출한다.
# postgres 컨테이너가 처음 기동될 때(볼륨이 비어 있을 때) 한 번만 적용된다.
set -euo pipefail

cd "$(dirname "$0")/.."
VERSION="${GUACAMOLE_VERSION:-$(grep -E '^GUACAMOLE_VERSION=' .env 2>/dev/null | cut -d= -f2 || true)}"
VERSION="${VERSION:-1.5.5}"

mkdir -p initdb
# 실패 시 빈 파일이 남으면 postgres 가 스키마 없이 초기화되므로, 임시 파일에 받은 뒤 옮긴다
tmp="$(mktemp initdb/initdb.sql.XXXXXX)"
trap 'rm -f "$tmp"' EXIT
docker run --rm "guacamole/guacamole:${VERSION}" /opt/guacamole/bin/initdb.sh --postgresql > "$tmp"
if ! grep -q 'CREATE TABLE' "$tmp"; then
  echo "오류: 스키마를 추출하지 못했습니다." >&2
  exit 1
fi
mv "$tmp" initdb/initdb.sql
trap - EXIT
echo "생성됨: $(pwd)/initdb/initdb.sql (Guacamole ${VERSION})"
