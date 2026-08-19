"""Wake-on-LAN magic packet construction and sending."""
from __future__ import annotations

import socket

from .config import InvalidMACError, normalize_mac

__all__ = ["build_magic_packet", "send_magic_packet", "InvalidMACError"]


def build_magic_packet(mac: str) -> bytes:
    normalized = normalize_mac(mac)
    mac_bytes = bytes.fromhex(normalized.replace(":", ""))
    return b"\xff" * 6 + mac_bytes * 16


def send_magic_packet(mac: str, broadcast_ip: str = "255.255.255.255", port: int = 9, repeat: int = 1) -> None:
    packet = build_magic_packet(mac)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        # Sin SO_BROADCAST, sendto() a una dirección de broadcast falla con
        # PermissionError aunque el proceso no sea root.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for _ in range(max(1, repeat)):
            sock.sendto(packet, (broadcast_ip, port))
