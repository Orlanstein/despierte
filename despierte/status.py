"""Host reachability checks via the system ping binary."""
from __future__ import annotations

import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, Optional


class Status(Enum):
    UNKNOWN = "unknown"
    ONLINE = "online"
    OFFLINE = "offline"


@dataclass
class HostStatus:
    status: Status = Status.UNKNOWN
    last_checked: Optional[float] = None


def ping_host(ip: str, timeout: float = 1.0) -> bool:
    if not ip:
        return False
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", str(max(1, int(timeout))), ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout + 2,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


class StatusMonitor:
    """Background pool that periodically pings all known hosts.

    Only ever touched from background threads created here plus the main
    thread reading snapshot()/last_error() — never call curses from these
    threads, the caller is responsible for redrawing after reading state.
    """

    def __init__(self, get_targets: Callable[[], Dict[str, str]], interval: float = 5.0, max_workers: int = 8):
        self._get_targets = get_targets
        self._interval = interval
        self._max_workers = max_workers
        self._lock = threading.Lock()
        self._results: Dict[str, HostStatus] = {}
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_error: Optional[str] = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def snapshot(self) -> Dict[str, HostStatus]:
        with self._lock:
            return dict(self._results)

    def last_error(self) -> Optional[str]:
        with self._lock:
            return self._last_error

    def refresh_now(self) -> None:
        threading.Thread(target=self._run_cycle, daemon=True).start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._run_cycle()
            self._stop.wait(self._interval)

    def _run_cycle(self) -> None:
        try:
            targets = self._get_targets()
            workers = min(self._max_workers, max(1, len(targets)))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {name: pool.submit(ping_host, ip) for name, ip in targets.items()}
                now = time.monotonic()
                updated: Dict[str, HostStatus] = {
                    name: HostStatus(
                        status=Status.ONLINE if fut.result() else Status.OFFLINE,
                        last_checked=now,
                    )
                    for name, fut in futures.items()
                }
            with self._lock:
                self._results.update(updated)
                self._last_error = None
        except Exception as exc:  # a background thread dying silently would hide real failures
            with self._lock:
                self._last_error = str(exc)
