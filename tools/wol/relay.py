#!/usr/bin/env python3
"""WoL 릴레이: 포털 백엔드의 요청을 받아 실습실 VLAN 안에서 매직 패킷을 보낸다.

매직 패킷(브로드캐스트)은 라우터를 넘지 못하므로, 실습실 PC 와 같은 VLAN 에 있는
상시 켜진 장비(라즈베리파이 등)에서 이 스크립트를 실행한다. 표준 라이브러리만 사용.

    RELAY_TOKEN=<긴 임의 문자열> python3 relay.py --listen 0.0.0.0 --port 8080 \
        --allow-from 10.0.5.20 --broadcast 10.20.30.255

API
    GET  /health                      -> {"ok": true}
    POST /wake  {"mac": "AA:BB:...", "broadcast": "10.20.30.255"(선택)}
         Authorization: Bearer <RELAY_TOKEN>

보안
    - 토큰 필수 (hmac.compare_digest 로 비교)
    - --allow-from 으로 포털 백엔드 IP 만 허용
    - 브로드캐스트 주소는 --broadcast(기본값)과 --allow-broadcast 에 적은 것만 허용
"""
from __future__ import annotations

import argparse
import hmac
import ipaddress
import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wol import parse_mac, send  # noqa: E402

log = logging.getLogger("wol-relay")


class Config:
    token: str = ""
    allow_from: list = []
    default_broadcast: str = "255.255.255.255"
    allowed_broadcasts: set[str] = set()
    port: int = 9


class Handler(BaseHTTPRequestHandler):
    server_version = "jarion-wol-relay/1"

    def _reply(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _client_allowed(self) -> bool:
        if not Config.allow_from:
            return True
        ip = ipaddress.ip_address(self.client_address[0])
        return any(ip in net for net in Config.allow_from)

    def do_GET(self):
        if self.path == "/health":
            return self._reply(200, {"ok": True})
        return self._reply(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/wake":
            return self._reply(404, {"error": "not found"})
        if not self._client_allowed():
            return self._reply(403, {"error": "forbidden"})
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or not hmac.compare_digest(auth[7:].encode(), Config.token.encode()):
            return self._reply(401, {"error": "unauthorized"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 4096:
                return self._reply(413, {"error": "too large"})
            body = json.loads(self.rfile.read(length) or b"{}")
            mac = str(body["mac"])
            parse_mac(mac)
            broadcast = str(body.get("broadcast") or Config.default_broadcast)
        except (KeyError, ValueError, json.JSONDecodeError) as e:
            return self._reply(400, {"error": f"bad request: {e}"})
        if broadcast not in Config.allowed_broadcasts:
            return self._reply(400, {"error": f"broadcast {broadcast} not allowed"})
        try:
            send([mac], broadcast, Config.port)
        except OSError as e:
            log.error("send failed: %s", e)
            return self._reply(500, {"error": str(e)})
        log.info("wake %s via %s from %s", mac, broadcast, self.client_address[0])
        return self._reply(200, {"ok": True})

    def log_message(self, fmt, *args):  # 기본 stderr 로그 대신 logging 사용
        log.debug(fmt, *args)


def main() -> int:
    p = argparse.ArgumentParser(description="JARION WoL 릴레이")
    p.add_argument("--listen", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--allow-from", action="append", default=[],
                   help="허용할 클라이언트 IP/CIDR (여러 번 지정 가능). 미지정 시 모두 허용")
    p.add_argument("--broadcast", default="255.255.255.255", help="기본 브로드캐스트 주소")
    p.add_argument("--allow-broadcast", action="append", default=[],
                   help="요청에서 지정을 허용할 추가 브로드캐스트 주소")
    p.add_argument("--wol-port", type=int, default=9)
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    token = os.environ.get("RELAY_TOKEN", "")
    if len(token) < 16:
        print("RELAY_TOKEN 환경 변수를 16자 이상으로 설정하세요", file=sys.stderr)
        return 2

    Config.token = token
    Config.allow_from = [ipaddress.ip_network(x, strict=False) for x in args.allow_from]
    Config.default_broadcast = args.broadcast
    Config.allowed_broadcasts = {args.broadcast, *args.allow_broadcast}
    Config.port = args.wol_port

    srv = ThreadingHTTPServer((args.listen, args.port), Handler)
    log.info("listening on %s:%d (broadcasts: %s)", args.listen, args.port,
             ", ".join(sorted(Config.allowed_broadcasts)))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
