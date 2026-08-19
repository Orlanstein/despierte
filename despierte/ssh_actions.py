"""Run predefined commands on remote hosts over SSH."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass
class SSHResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


def run_ssh_action(
    user: str,
    host: str,
    cmd: str,
    port: int = 22,
    connect_timeout: int = 5,
    timeout: float = 30.0,
) -> SSHResult:
    target = f"{user}@{host}" if user else host
    argv = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={connect_timeout}",
        "-p", str(port),
        target,
        cmd,
    ]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return SSHResult(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
    except subprocess.TimeoutExpired:
        return SSHResult(returncode=-1, stdout="", stderr="Tiempo de espera agotado.", timed_out=True)
    except OSError as exc:
        return SSHResult(returncode=-1, stdout="", stderr=str(exc))
