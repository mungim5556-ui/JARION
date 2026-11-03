#!/usr/bin/env python3
"""Wake-on-LAN 매직 패킷 전송 도구 (표준 라이브러리만 사용).

매직 패킷은 브로드캐스트라 라우터를 넘지 못하므로, 실습실 PC와 같은
VLAN(서브넷)에 있는 장비(릴레이: 라즈베리파이, 상시 켜진 PC 등)에서 실행해야 한다.

사용 예:
    python3 wol.py AA:BB:CC:DD:EE:FF
    python3 wol.py AA-BB-CC-DD-EE-FF 11:22:33:44:55:66 --broadcast 10.20.30.255
    python3 wol.py --file machines.csv          # CSV 첫 열이 MAC (헤더 'mac' 허용)
"""
from __future__ import annotations

import argparse
import csv
import re
import socket
import sys

MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}([:\-]?[0-9A-Fa-f]{2}){5}$")


def parse_mac(mac: str) -> bytes:
    mac = mac.strip()
    if not MAC_RE.match(mac):
        raise ValueError(f"잘못된 MAC 주소: {mac!r}")
    return bytes.fromhex(re.sub(r"[:\-]", "", mac))


def magic_packet(mac: str) -> bytes:
    return b"\xff" * 6 + parse_mac(mac) * 16


def send(macs: list[str], broadcast: str, port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for mac in macs:
            sock.sendto(magic_packet(mac), (broadcast, port))
            print(f"전송: {mac} -> {broadcast}:{port}")


def read_csv(path: str) -> list[str]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = [r for r in csv.reader(f) if r and r[0].strip()]
    if rows and rows[0][0].strip().lower() == "mac":
        rows = rows[1:]
    return [r[0] for r in rows]


def main() -> int:
    p = argparse.ArgumentParser(description="Wake-on-LAN 매직 패킷 전송")
    p.add_argument("macs", nargs="*", help="대상 MAC 주소")
    p.add_argument("--file", help="MAC 목록 CSV (첫 열)")
    p.add_argument("--broadcast", default="255.255.255.255",
                   help="브로드캐스트 주소 (예: 10.20.30.255). 기본 255.255.255.255")
    p.add_argument("--port", type=int, default=9, help="UDP 포트 (기본 9, 일부 장비는 7)")
    args = p.parse_args()

    macs = list(args.macs)
    if args.file:
        macs += read_csv(args.file)
    if not macs:
        p.error("MAC 주소 또는 --file 을 지정하세요")

    try:
        send(macs, args.broadcast, args.port)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
