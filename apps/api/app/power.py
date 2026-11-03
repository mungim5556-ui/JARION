"""PC 전원/상태: WoL 릴레이 호출과 RDP 포트 확인."""
import logging
import socket
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

import httpx

from .models import Machine

log = logging.getLogger(__name__)


class WakeError(Exception):
    pass


class Waker(Protocol):
    def wake(self, machine: Machine) -> None: ...


class Prober(Protocol):
    def probe(self, machines: Iterable[Machine]) -> dict[int, bool]: ...


class RelayWaker:
    """실습실 VLAN 안의 릴레이(tools/wol/relay.py)에 매직 패킷 전송을 요청한다."""

    def __init__(self, token: str, timeout: float = 5.0):
        self.token = token
        self.timeout = timeout

    def wake(self, machine: Machine) -> None:
        lab = machine.lab
        if not lab.wol_relay_url:
            raise WakeError(f"{lab.name} 실습실에 WoL 릴레이가 설정되지 않았습니다")
        try:
            r = httpx.post(
                lab.wol_relay_url.rstrip("/") + "/wake",
                json={"mac": machine.mac, "broadcast": lab.broadcast_address},
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=self.timeout,
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise WakeError(f"WoL 릴레이 호출 실패: {e}") from e


class TcpProber:
    """RDP 포트가 열려 있으면 켜져 있고 로그인 가능한 상태로 본다."""

    def __init__(self, timeout: float = 1.5, workers: int = 32):
        self.timeout = timeout
        self.workers = workers

    def _check(self, host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=self.timeout):
                return True
        except OSError:
            return False

    def probe(self, machines: Iterable[Machine]) -> dict[int, bool]:
        targets = [(m.id, m.hostname, m.rdp_port) for m in machines]
        if not targets:
            return {}
        with ThreadPoolExecutor(max_workers=min(self.workers, len(targets))) as ex:
            results = ex.map(lambda t: self._check(t[1], t[2]), targets)
            return {t[0]: ok for t, ok in zip(targets, results)}
