"""Persistent storage for despierte's host list."""
from __future__ import annotations

import ipaddress
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

MAC_RE = re.compile(
    r"^([0-9A-Fa-f]{2})([:-]?)"
    r"([0-9A-Fa-f]{2})\2([0-9A-Fa-f]{2})\2([0-9A-Fa-f]{2})\2([0-9A-Fa-f]{2})\2([0-9A-Fa-f]{2})$"
)

DESTRUCTIVE_HINTS = ("shutdown", "poweroff", "reboot", "halt", "rm ")


class ConfigError(Exception):
    """Raised when the on-disk config is missing required structure or is corrupt."""


class InvalidMACError(ValueError):
    """Raised when a MAC address string doesn't parse."""


class InvalidIPError(ValueError):
    """Raised when an IPv4 address string doesn't parse."""


def normalize_mac(mac: str) -> str:
    match = MAC_RE.match(mac.strip())
    if not match:
        raise InvalidMACError(f"MAC inválida: {mac!r}")
    groups = [match.group(1), match.group(3), match.group(4), match.group(5), match.group(6), match.group(7)]
    return ":".join(g.upper() for g in groups)


def validate_ipv4(ip: str) -> str:
    try:
        return str(ipaddress.IPv4Address(ip.strip()))
    except ValueError as exc:
        raise InvalidIPError(f"IP inválida: {ip!r}") from exc


def looks_destructive(cmd: str) -> bool:
    lowered = cmd.lower()
    return any(hint in lowered for hint in DESTRUCTIVE_HINTS)


@dataclass
class SSHAction:
    label: str
    cmd: str
    destructive: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "SSHAction":
        return cls(label=data["label"], cmd=data["cmd"], destructive=bool(data.get("destructive", False)))

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Host:
    name: str
    mac: str
    ip: str = ""
    broadcast: str = "255.255.255.255"
    wol_port: int = 9
    ssh_user: str = ""
    ssh_host: str = ""
    ssh_port: int = 22
    actions: List[SSHAction] = field(default_factory=list)

    def resolved_ssh_host(self) -> str:
        return self.ssh_host or self.ip

    @classmethod
    def from_dict(cls, data: dict) -> "Host":
        actions = [SSHAction.from_dict(a) for a in data.get("actions", [])]
        return cls(
            name=data["name"],
            mac=data["mac"],
            ip=data.get("ip", ""),
            broadcast=data.get("broadcast", "255.255.255.255"),
            wol_port=int(data.get("wol_port", 9)),
            ssh_user=data.get("ssh_user", ""),
            ssh_host=data.get("ssh_host", ""),
            ssh_port=int(data.get("ssh_port", 22)),
            actions=actions,
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "mac": self.mac,
            "ip": self.ip,
            "broadcast": self.broadcast,
            "wol_port": self.wol_port,
            "ssh_user": self.ssh_user,
            "ssh_host": self.ssh_host,
            "ssh_port": self.ssh_port,
            "actions": [a.to_dict() for a in self.actions],
        }


def default_config_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "despierte" / "hosts.json"


def load_config(path: Optional[Path] = None) -> List[Host]:
    path = path or default_config_path()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Config JSON inválido en {path}: {exc}") from exc
    try:
        return [Host.from_dict(h) for h in raw.get("hosts", [])]
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError(f"Config con estructura inválida en {path}: {exc}") from exc


def save_config(hosts: List[Host], path: Optional[Path] = None) -> None:
    path = path or default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"hosts": [h.to_dict() for h in hosts]}
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp_path, path)


def find_host(hosts: List[Host], name: str) -> Optional[Host]:
    for host in hosts:
        if host.name == name:
            return host
    return None
