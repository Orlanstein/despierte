"""Shared test fixtures."""
from despierte.config import Host


def make_host(name="pc", mac="AA:BB:CC:DD:EE:FF", ip="192.168.1.10", **overrides) -> Host:
    defaults = dict(name=name, mac=mac, ip=ip)
    defaults.update(overrides)
    return Host(**defaults)
