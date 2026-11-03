#!/bin/sh
# 최초 기동 시 1회: 포털용 DB/계정 생성
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v pw="$JARION_DB_PASSWORD" <<'SQL'
CREATE USER jarion WITH PASSWORD :'pw';
CREATE DATABASE jarion OWNER jarion;
SQL
