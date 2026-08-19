"""Command-line entry point: scriptable subcommands plus TUI launch."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from .config import (
    ConfigError,
    Host,
    InvalidIPError,
    InvalidMACError,
    default_config_path,
    find_host,
    load_config,
    looks_destructive,
    normalize_mac,
    save_config,
    validate_ipv4,
)
from .ssh_actions import run_ssh_action
from .status import ping_host
from .wol import send_magic_packet


def _config_path(args: argparse.Namespace) -> Path:
    return Path(args.config).expanduser() if args.config else default_config_path()


def _load(args: argparse.Namespace) -> List[Host]:
    try:
        return load_config(_config_path(args))
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)


def cmd_list(args: argparse.Namespace) -> int:
    hosts = _load(args)
    if args.json:
        print(json.dumps([h.to_dict() for h in hosts], indent=2, ensure_ascii=False))
        return 0
    if not hosts:
        print("No hay equipos configurados. Usá 'despierte add' para agregar uno.")
        return 0
    for host in hosts:
        ssh_target = f"{host.ssh_user or '-'}@{host.resolved_ssh_host() or '-'}:{host.ssh_port}"
        print(f"{host.name:<20} {host.mac:<18} {host.ip or '-':<15} ssh={ssh_target}")
    return 0


def cmd_wake(args: argparse.Namespace) -> int:
    hosts = _load(args)
    if args.all:
        targets = hosts
    else:
        targets = []
        for name in args.names:
            host = find_host(hosts, name)
            if host is None:
                print(f"error: equipo desconocido: {name}", file=sys.stderr)
                return 2
            targets.append(host)
    if not targets:
        print("error: no se especificaron equipos (usá nombres o --all)", file=sys.stderr)
        return 2
    for host in targets:
        try:
            send_magic_packet(host.mac, host.broadcast, host.wol_port)
            print(f"magic packet enviado a {host.name} ({host.mac})")
        except (InvalidMACError, OSError) as exc:
            print(f"error: {host.name}: {exc}", file=sys.stderr)
            return 1
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    hosts = _load(args)
    host = find_host(hosts, args.name)
    if host is None:
        print(f"error: equipo desconocido: {args.name}", file=sys.stderr)
        return 2
    if not host.ip:
        print(f"{host.name}: sin IP configurada")
        return 2
    online = ping_host(host.ip)
    print(f"{host.name}: {'online' if online else 'offline'}")
    return 0 if online else 1


def _host_from_args(args: argparse.Namespace, base: Optional[Host] = None) -> Host:
    name = getattr(args, "name", None) or (base.name if base else "")
    raw_mac = getattr(args, "mac", None)
    mac = normalize_mac(raw_mac) if raw_mac else (base.mac if base else "")
    if not mac:
        raise InvalidMACError("--mac es obligatorio")
    ip = args.ip if getattr(args, "ip", None) is not None else (base.ip if base else "")
    if ip:
        validate_ipv4(ip)
    broadcast = args.broadcast if getattr(args, "broadcast", None) is not None else (
        base.broadcast if base else "255.255.255.255"
    )
    wol_port = args.wol_port if getattr(args, "wol_port", None) is not None else (base.wol_port if base else 9)
    ssh_user = args.ssh_user if getattr(args, "ssh_user", None) is not None else (base.ssh_user if base else "")
    ssh_host = args.ssh_host if getattr(args, "ssh_host", None) is not None else (base.ssh_host if base else "")
    ssh_port = args.ssh_port if getattr(args, "ssh_port", None) is not None else (base.ssh_port if base else 22)
    actions = base.actions if base else []
    return Host(
        name=name, mac=mac, ip=ip, broadcast=broadcast, wol_port=wol_port,
        ssh_user=ssh_user, ssh_host=ssh_host, ssh_port=ssh_port, actions=actions,
    )


def cmd_add(args: argparse.Namespace) -> int:
    hosts = _load(args)
    if find_host(hosts, args.name) is not None:
        print(f"error: ya existe un equipo llamado {args.name}", file=sys.stderr)
        return 1
    try:
        host = _host_from_args(args)
    except (InvalidMACError, InvalidIPError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    hosts.append(host)
    save_config(hosts, _config_path(args))
    print(f"agregado: {host.name}")
    return 0


def cmd_edit(args: argparse.Namespace) -> int:
    hosts = _load(args)
    host = find_host(hosts, args.name)
    if host is None:
        print(f"error: equipo desconocido: {args.name}", file=sys.stderr)
        return 2
    try:
        updated = _host_from_args(args, base=host)
    except (InvalidMACError, InvalidIPError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    hosts[hosts.index(host)] = updated
    save_config(hosts, _config_path(args))
    print(f"actualizado: {updated.name}")
    return 0


def cmd_rm(args: argparse.Namespace) -> int:
    hosts = _load(args)
    host = find_host(hosts, args.name)
    if host is None:
        print(f"error: equipo desconocido: {args.name}", file=sys.stderr)
        return 2
    if not args.yes:
        answer = input(f"¿Borrar {host.name}? [y/N] ").strip().lower()
        if answer != "y":
            print("cancelado")
            return 1
    hosts.remove(host)
    save_config(hosts, _config_path(args))
    print(f"borrado: {host.name}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    hosts = _load(args)
    host = find_host(hosts, args.name)
    if host is None:
        print(f"error: equipo desconocido: {args.name}", file=sys.stderr)
        return 2
    if not args.cmd and not args.action:
        print("error: especificá una acción configurada o --cmd", file=sys.stderr)
        return 2
    if args.cmd:
        cmd = args.cmd
        destructive = looks_destructive(cmd)
    else:
        action = next((a for a in host.actions if a.label == args.action), None)
        if action is None:
            print(f"error: acción desconocida: {args.action}", file=sys.stderr)
            return 2
        cmd = action.cmd
        destructive = action.destructive
    if destructive and not args.yes:
        answer = input(f"Esto es una acción destructiva ({cmd}). ¿Continuar? [y/N] ").strip().lower()
        if answer != "y":
            print("cancelado")
            return 1
    result = run_ssh_action(host.ssh_user, host.resolved_ssh_host(), cmd, port=host.ssh_port)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.timed_out:
        print("error: tiempo de espera agotado", file=sys.stderr)
    return result.returncode if result.returncode >= 0 else 1


def _add_host_flags(parser: argparse.ArgumentParser, mac_required: bool) -> None:
    parser.add_argument("--mac", required=mac_required)
    parser.add_argument("--ip")
    parser.add_argument("--broadcast")
    parser.add_argument("--wol-port", dest="wol_port", type=int)
    parser.add_argument("--ssh-user", dest="ssh_user")
    parser.add_argument("--ssh-host", dest="ssh_host")
    parser.add_argument("--ssh-port", dest="ssh_port", type=int)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="despierte", description="Gestor de equipos y Wake-on-LAN.")
    parser.add_argument("--config", help="ruta alternativa al archivo de configuración JSON")
    sub = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("list", help="listar equipos configurados")
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=cmd_list)

    p_wake = sub.add_parser("wake", help="enviar magic packet(s)")
    p_wake.add_argument("names", nargs="*")
    p_wake.add_argument("--all", action="store_true")
    p_wake.set_defaults(func=cmd_wake)

    p_status = sub.add_parser("status", help="chequear estado online/offline")
    p_status.add_argument("name")
    p_status.set_defaults(func=cmd_status)

    p_add = sub.add_parser("add", help="agregar un equipo")
    p_add.add_argument("--name", required=True)
    _add_host_flags(p_add, mac_required=True)
    p_add.set_defaults(func=cmd_add)

    p_edit = sub.add_parser("edit", help="editar un equipo existente")
    p_edit.add_argument("name")
    _add_host_flags(p_edit, mac_required=False)
    p_edit.set_defaults(func=cmd_edit)

    p_rm = sub.add_parser("rm", help="borrar un equipo")
    p_rm.add_argument("name")
    p_rm.add_argument("--yes", action="store_true")
    p_rm.set_defaults(func=cmd_rm)

    p_run = sub.add_parser("run", help="ejecutar una acción SSH en un equipo")
    p_run.add_argument("name")
    p_run.add_argument("action", nargs="?")
    p_run.add_argument("--cmd")
    p_run.add_argument("--yes", action="store_true")
    p_run.set_defaults(func=cmd_run)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        from .tui import run as run_tui
        return run_tui(_config_path(args))
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
