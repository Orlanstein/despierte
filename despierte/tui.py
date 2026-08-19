"""Curses-based interactive interface for despierte.

Hard invariant: only the main thread (running inside curses.wrapper) ever
touches a curses window object. Background threads (StatusMonitor, SSH
action workers) only ever write to plain Python state guarded by a lock or
a queue — the main loop reads that state and redraws.
"""
from __future__ import annotations

import curses
import queue
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .config import (
    ConfigError,
    Host,
    InvalidIPError,
    InvalidMACError,
    SSHAction,
    find_host,
    load_config,
    looks_destructive,
    normalize_mac,
    save_config,
    validate_ipv4,
)
from .ssh_actions import SSHResult, run_ssh_action
from .status import Status, StatusMonitor
from .wol import send_magic_packet

COLOR_ONLINE = 1
COLOR_OFFLINE = 2
COLOR_UNKNOWN = 3
COLOR_HEADER = 4
COLOR_SELECTED = 5
COLOR_ERROR = 6

FORM_FIELDS = [
    ("name", "Name"),
    ("mac", "MAC"),
    ("ip", "IP"),
    ("broadcast", "Broadcast"),
    ("wol_port", "WOL port"),
    ("ssh_user", "SSH user"),
    ("ssh_host", "SSH host (blank = use IP)"),
    ("ssh_port", "SSH port"),
]

FORM_DEFAULTS = {
    "broadcast": "255.255.255.255",
    "wol_port": "9",
    "ssh_port": "22",
}


def _init_colors() -> None:
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(COLOR_ONLINE, curses.COLOR_GREEN, -1)
    curses.init_pair(COLOR_OFFLINE, curses.COLOR_RED, -1)
    curses.init_pair(COLOR_UNKNOWN, curses.COLOR_YELLOW, -1)
    curses.init_pair(COLOR_HEADER, curses.COLOR_CYAN, -1)
    curses.init_pair(COLOR_SELECTED, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(COLOR_ERROR, curses.COLOR_WHITE, curses.COLOR_RED)


STATUS_GLYPH = {
    Status.ONLINE: ("●", COLOR_ONLINE),
    Status.OFFLINE: ("○", COLOR_OFFLINE),
    Status.UNKNOWN: ("?", COLOR_UNKNOWN),
}


class ConfirmDialog:
    def __init__(self, stdscr, prompt: str):
        self.stdscr = stdscr
        self.prompt = prompt

    def run(self) -> bool:
        height, width = self.stdscr.getmaxyx()
        box_w = min(width - 2, max(24, len(self.prompt) + 4))
        win = curses.newwin(3, box_w, height // 2 - 1, max(0, (width - box_w) // 2))
        win.keypad(True)
        win.border()
        win.addstr(1, 2, self.prompt[: box_w - 4])
        win.refresh()
        curses.halfdelay(5)
        while True:
            ch = win.getch()
            if ch in (ord("y"), ord("Y")):
                return True
            if ch == -1:
                continue
            return False


class TextPrompt:
    def __init__(self, stdscr, label: str, initial: str = ""):
        self.stdscr = stdscr
        self.label = label
        self.initial = initial

    def run(self) -> Optional[str]:
        height, width = self.stdscr.getmaxyx()
        win = curses.newwin(3, width - 2, max(0, height - 4), 1)
        win.border()
        win.addstr(1, 2, self.label)
        win.refresh()
        curses.curs_set(1)
        curses.echo()
        win.timeout(-1)  # blocking input while typing
        try:
            max_len = max(1, width - len(self.label) - 6)
            field_x = 2 + len(self.label)
            if self.initial:
                win.addstr(1, field_x, self.initial[:max_len])
                win.move(1, field_x + len(self.initial[:max_len]))
            raw = win.getstr(1, field_x, max_len)
            return raw.decode("utf-8", errors="replace") if raw else self.initial
        except (KeyboardInterrupt, curses.error):
            return None
        finally:
            curses.noecho()
            curses.curs_set(0)
            curses.halfdelay(5)


class TextViewer:
    """Scrollable read-only panel, closed with Enter/Esc/q."""

    def __init__(self, stdscr, lines: List[str], title: str = ""):
        self.stdscr = stdscr
        self.lines = lines
        self.title = title

    def run(self) -> None:
        height, width = self.stdscr.getmaxyx()
        win_h = max(10, min(height - 2, len(self.lines) + 4))
        win_w = max(20, width - 4)
        win = curses.newwin(win_h, win_w, max(0, (height - win_h) // 2), max(0, (width - win_w) // 2))
        win.keypad(True)
        offset = 0
        body_h = win_h - 3
        max_offset = max(0, len(self.lines) - body_h)
        curses.halfdelay(5)
        while True:
            win.erase()
            win.border()
            if self.title:
                win.addstr(0, 2, f" {self.title} "[: win_w - 4])
            for i, line in enumerate(self.lines[offset:offset + body_h]):
                win.addstr(1 + i, 2, line[: win_w - 4])
            win.addstr(win_h - 2, 2, "↑↓ scroll · enter/esc/q close"[: win_w - 4], curses.A_DIM)
            win.refresh()
            ch = win.getch()
            if ch in (curses.KEY_UP, ord("k")):
                offset = max(0, offset - 1)
            elif ch in (curses.KEY_DOWN, ord("j")):
                offset = min(max_offset, offset + 1)
            elif ch in (10, 13, 27, ord("q")):
                return


class ActionsEditor:
    def __init__(self, stdscr, actions: List[SSHAction]):
        self.stdscr = stdscr
        self.actions = list(actions)
        self.cursor = 0

    def run(self) -> List[SSHAction]:
        height, width = self.stdscr.getmaxyx()
        win_h = min(height - 4, max(8, len(self.actions) + 6))
        win_w = min(width - 4, 64)
        win = curses.newwin(win_h, win_w, max(0, (height - win_h) // 2), max(0, (width - win_w) // 2))
        win.keypad(True)
        curses.halfdelay(5)
        while True:
            win.erase()
            win.border()
            win.addstr(0, 2, " SSH actions ")
            if not self.actions:
                win.addstr(1, 2, "(no actions yet)")
            for i, action in enumerate(self.actions):
                mark = "!" if action.destructive else " "
                attr = curses.A_REVERSE if i == self.cursor else curses.A_NORMAL
                win.addstr(1 + i, 2, f"{mark} {action.label}: {action.cmd}"[: win_w - 4], attr)
            win.addstr(win_h - 2, 2, "a:add  d:delete  esc:back"[: win_w - 4], curses.A_DIM)
            win.refresh()
            ch = win.getch()
            if ch in (curses.KEY_UP, ord("k")):
                self.cursor = max(0, self.cursor - 1)
            elif ch in (curses.KEY_DOWN, ord("j")):
                self.cursor = min(max(0, len(self.actions) - 1), self.cursor + 1)
            elif ch == ord("a"):
                label = TextPrompt(self.stdscr, "Action name: ").run()
                if not label:
                    continue
                cmd = TextPrompt(self.stdscr, "Command: ").run()
                if not cmd:
                    continue
                self.actions.append(SSHAction(label=label, cmd=cmd, destructive=looks_destructive(cmd)))
                self.cursor = len(self.actions) - 1
            elif ch == ord("d") and self.actions:
                del self.actions[self.cursor]
                self.cursor = max(0, self.cursor - 1)
            elif ch == 27:
                return self.actions


class SSHActionModal:
    """Lets the user pick a configured SSH action, or type a custom command."""

    def __init__(self, stdscr, host: Host):
        self.stdscr = stdscr
        self.host = host

    def run(self) -> Optional[Tuple[str, str, bool]]:
        options: List[Optional[SSHAction]] = list(self.host.actions) + [None]
        cursor = 0
        height, width = self.stdscr.getmaxyx()
        win_h = min(height - 4, len(options) + 4)
        win_w = min(width - 4, 60)
        win = curses.newwin(win_h, win_w, max(0, (height - win_h) // 2), max(0, (width - win_w) // 2))
        win.keypad(True)
        curses.halfdelay(5)
        while True:
            win.erase()
            win.border()
            win.addstr(0, 2, f" SSH actions: {self.host.name} "[: win_w - 4])
            for i, opt in enumerate(options):
                label = opt.label if opt else "Custom command…"
                marker = ">" if i == cursor else " "
                attr = curses.A_REVERSE if i == cursor else curses.A_NORMAL
                win.addstr(1 + i, 2, f"{marker} {label}"[: win_w - 4], attr)
            win.addstr(win_h - 2, 2, "enter:run  esc:cancel"[: win_w - 4], curses.A_DIM)
            win.refresh()
            ch = win.getch()
            if ch in (curses.KEY_UP, ord("k")):
                cursor = max(0, cursor - 1)
            elif ch in (curses.KEY_DOWN, ord("j")):
                cursor = min(len(options) - 1, cursor + 1)
            elif ch in (10, 13):
                chosen = options[cursor]
                if chosen is None:
                    cmd = TextPrompt(self.stdscr, "Command: ").run()
                    if not cmd:
                        continue
                    return ("custom command", cmd, looks_destructive(cmd))
                return (chosen.label, chosen.cmd, chosen.destructive)
            elif ch == 27:
                return None


class HostFormScreen:
    def __init__(self, stdscr, base: Optional[Host] = None):
        self.stdscr = stdscr
        self.base = base
        if base:
            self.values = {
                "name": base.name,
                "mac": base.mac,
                "ip": base.ip,
                "broadcast": base.broadcast,
                "wol_port": str(base.wol_port),
                "ssh_user": base.ssh_user,
                "ssh_host": base.ssh_host,
                "ssh_port": str(base.ssh_port),
            }
            self.actions = list(base.actions)
        else:
            self.values = {key: FORM_DEFAULTS.get(key, "") for key, _ in FORM_FIELDS}
            self.actions = []
        self.errors: Dict[str, str] = {}
        self.cursor = 0

    def _validate(self) -> bool:
        self.errors.clear()
        if not self.values["name"].strip():
            self.errors["name"] = "required"
        try:
            normalize_mac(self.values["mac"])
        except InvalidMACError:
            self.errors["mac"] = "invalid format"
        for key in ("ip", "broadcast"):
            value = self.values[key].strip()
            if value:
                try:
                    validate_ipv4(value)
                except InvalidIPError:
                    self.errors[key] = "invalid IP"
        for key in ("wol_port", "ssh_port"):
            value = self.values[key].strip()
            if value and not value.isdigit():
                self.errors[key] = "must be numeric"
        return not self.errors

    def _build_host(self) -> Host:
        return Host(
            name=self.values["name"].strip(),
            mac=normalize_mac(self.values["mac"]),
            ip=self.values["ip"].strip(),
            broadcast=self.values["broadcast"].strip() or "255.255.255.255",
            wol_port=int(self.values["wol_port"] or 9),
            ssh_user=self.values["ssh_user"].strip(),
            ssh_host=self.values["ssh_host"].strip(),
            ssh_port=int(self.values["ssh_port"] or 22),
            actions=self.actions,
        )

    def run(self) -> Optional[Host]:
        height, width = self.stdscr.getmaxyx()
        win_h = min(height - 2, len(FORM_FIELDS) + 8)
        win_w = min(width - 4, 74)
        win = curses.newwin(win_h, win_w, max(0, (height - win_h) // 2), max(0, (width - win_w) // 2))
        win.keypad(True)
        curses.halfdelay(5)
        num_fields = len(FORM_FIELDS)
        total_rows = num_fields + 1  # + the "actions" row
        while True:
            win.erase()
            win.border()
            title = " Edit host " if self.base else " New host "
            win.addstr(0, 2, title)
            for i, (key, label) in enumerate(FORM_FIELDS):
                attr = curses.A_REVERSE if i == self.cursor else curses.A_NORMAL
                error = f"  ⚠ {self.errors[key]}" if key in self.errors else ""
                win.addstr(1 + i, 2, f"{label:<26} {self.values[key]}{error}"[: win_w - 4], attr)
            actions_attr = curses.A_REVERSE if self.cursor == num_fields else curses.A_NORMAL
            win.addstr(
                1 + num_fields, 2,
                f"SSH actions ({len(self.actions)}) — enter to edit"[: win_w - 4],
                actions_attr,
            )
            hint_row = win.getmaxyx()[0] - 2
            win.addstr(
                hint_row, 2,
                "↑↓ move · enter edit · s save · esc cancel"[: win_w - 4],
                curses.A_DIM,
            )
            win.refresh()
            ch = win.getch()
            if ch in (curses.KEY_UP, ord("k")):
                self.cursor = max(0, self.cursor - 1)
            elif ch in (curses.KEY_DOWN, ord("j")):
                self.cursor = min(total_rows - 1, self.cursor + 1)
            elif ch in (10, 13):
                if self.cursor < num_fields:
                    key, label = FORM_FIELDS[self.cursor]
                    new_value = TextPrompt(self.stdscr, f"{label}: ", self.values[key]).run()
                    if new_value is not None:
                        self.values[key] = new_value
                else:
                    self.actions = ActionsEditor(self.stdscr, self.actions).run()
            elif ch == ord("s"):
                if self._validate():
                    return self._build_host()
            elif ch == 27:
                return None


class App:
    def __init__(self, stdscr, config_path: Optional[Path] = None):
        self.stdscr = stdscr
        self.config_path = config_path
        self.hosts: List[Host] = []
        self.cursor = 0
        self.selected: set = set()
        self.filter_text = ""
        self.message = ""
        self.dirty = True
        self.ssh_queue: "queue.Queue[Tuple[str, SSHResult]]" = queue.Queue()
        self.pending_ssh: Optional[str] = None

        try:
            self.hosts = load_config(self.config_path)
        except ConfigError as exc:
            self.message = f"config error: {exc}"

        self.monitor = StatusMonitor(self._ping_targets, interval=5.0)
        self.monitor.start()

    def _ping_targets(self) -> Dict[str, str]:
        return {host.name: host.ip for host in self.hosts if host.ip}

    def visible_hosts(self) -> List[Host]:
        if not self.filter_text:
            return self.hosts
        needle = self.filter_text.lower()
        return [h for h in self.hosts if needle in h.name.lower()]

    def save(self) -> None:
        try:
            save_config(self.hosts, self.config_path)
        except OSError as exc:
            self.message = f"error saving config: {exc}"

    def run(self) -> None:
        curses.curs_set(0)
        self.stdscr.keypad(True)
        _init_colors()
        curses.halfdelay(5)
        try:
            while True:
                if self.dirty:
                    self.draw()
                    self.dirty = False
                self._drain_ssh_queue()
                ch = self.stdscr.getch()
                if ch == -1:
                    continue
                if ch == curses.KEY_RESIZE:
                    self.dirty = True
                    continue
                self.dirty = True
                if not self.handle_key(ch):
                    break
        finally:
            self.monitor.stop()

    def _drain_ssh_queue(self) -> None:
        try:
            while True:
                label, result = self.ssh_queue.get_nowait()
                self.pending_ssh = None
                self.dirty = True
                self.show_ssh_result(label, result)
        except queue.Empty:
            pass

    def draw(self) -> None:
        stdscr = self.stdscr
        stdscr.erase()
        height, width = stdscr.getmaxyx()

        title = " despierte — host manager "
        stdscr.attron(curses.color_pair(COLOR_HEADER) | curses.A_BOLD)
        stdscr.addstr(0, max(0, (width - len(title)) // 2), title[:width])
        stdscr.attroff(curses.color_pair(COLOR_HEADER) | curses.A_BOLD)

        hosts = self.visible_hosts()
        header = f"    {'Name':<18} {'MAC':<18} {'IP':<15} Status"
        if height > 2:
            stdscr.addstr(2, 0, header[:width], curses.A_UNDERLINE)

        statuses = self.monitor.snapshot()
        row = 3
        for idx, host in enumerate(hosts):
            if row >= height - 3:
                break
            sel_mark = "x" if id(host) in self.selected else " "
            cursor_mark = ">" if idx == self.cursor else " "
            host_status = statuses.get(host.name)
            glyph, color = STATUS_GLYPH[host_status.status if host_status else Status.UNKNOWN]
            line = f"{cursor_mark} [{sel_mark}] {host.name:<18} {host.mac:<18} {(host.ip or '-'):<15} "
            attr = curses.color_pair(COLOR_SELECTED) if idx == self.cursor else curses.A_NORMAL
            stdscr.addstr(row, 0, line[:width], attr)
            if len(line) < width:
                stdscr.addstr(row, len(line), glyph, curses.color_pair(color) | curses.A_BOLD)
            row += 1

        if not hosts and height > 4:
            stdscr.addstr(4, 2, "No hosts yet. Press 'n' to add one.")

        if height >= 2:
            footer = (
                "q quit  ?:help  ↑↓ move  space select  w wake  n new  "
                "e edit  d delete  s ssh  r refresh  / filter"
            )
            stdscr.addstr(height - 2, 0, footer[:width - 1], curses.A_DIM)
        if self.filter_text and height >= 3:
            stdscr.addstr(height - 3, 0, f"filter: {self.filter_text}"[:width - 1])
        if self.message and height >= 1:
            stdscr.addstr(height - 1, 0, self.message[:width - 1], curses.color_pair(COLOR_ERROR))
        stdscr.noutrefresh()
        curses.doupdate()

    def handle_key(self, ch: int) -> bool:
        self.message = ""
        hosts = self.visible_hosts()
        if ch in (ord("q"), 27):
            return False
        elif ch in (curses.KEY_UP, ord("k")):
            self.cursor = max(0, self.cursor - 1)
        elif ch in (curses.KEY_DOWN, ord("j")):
            self.cursor = min(max(0, len(hosts) - 1), self.cursor + 1)
        elif ch == ord(" "):
            if hosts:
                host = hosts[self.cursor]
                if id(host) in self.selected:
                    self.selected.discard(id(host))
                else:
                    self.selected.add(id(host))
        elif ch == ord("a"):
            self.selected = {id(h) for h in hosts}
        elif ch == ord("A"):
            self.selected.clear()
        elif ch in (curses.KEY_ENTER, 10, 13, ord("w")):
            self.action_wake(hosts)
        elif ch == ord("n"):
            self.action_new_host()
        elif ch == ord("e"):
            self.action_edit_host(hosts)
        elif ch == ord("d"):
            self.action_delete(hosts)
        elif ch == ord("s"):
            self.action_ssh_menu(hosts)
        elif ch == ord("r"):
            self.monitor.refresh_now()
            self.message = "refreshing status..."
        elif ch == ord("/"):
            self.action_filter()
        elif ch == ord("?"):
            self.show_help()
        self.cursor = min(self.cursor, max(0, len(self.visible_hosts()) - 1))
        return True

    def action_wake(self, hosts: List[Host]) -> None:
        targets = [h for h in hosts if id(h) in self.selected] or ([hosts[self.cursor]] if hosts else [])
        if not targets:
            return
        for host in targets:
            try:
                send_magic_packet(host.mac, host.broadcast, host.wol_port)
            except (InvalidMACError, OSError) as exc:
                self.message = f"error waking {host.name}: {exc}"
                return
        self.message = "magic packet sent to: " + ", ".join(h.name for h in targets)

    def action_new_host(self) -> None:
        host = HostFormScreen(self.stdscr).run()
        if host is not None:
            self.hosts.append(host)
            self.save()
            self.message = f"added: {host.name}"

    def action_edit_host(self, hosts: List[Host]) -> None:
        if not hosts:
            return
        original = hosts[self.cursor]
        updated = HostFormScreen(self.stdscr, base=original).run()
        if updated is not None:
            self.hosts[self.hosts.index(original)] = updated
            self.save()
            self.message = f"updated: {updated.name}"

    def action_delete(self, hosts: List[Host]) -> None:
        targets = [h for h in hosts if id(h) in self.selected] or ([hosts[self.cursor]] if hosts else [])
        if not targets:
            return
        names = ", ".join(h.name for h in targets)
        if not ConfirmDialog(self.stdscr, f"Delete {names}? [y/N]").run():
            return
        for host in targets:
            self.hosts.remove(host)
            self.selected.discard(id(host))
        self.save()
        self.message = f"deleted: {names}"

    def action_filter(self) -> None:
        text = TextPrompt(self.stdscr, "Filter by name: ", self.filter_text).run()
        if text is not None:
            self.filter_text = text
            self.cursor = 0

    def action_ssh_menu(self, hosts: List[Host]) -> None:
        if not hosts:
            return
        host = hosts[self.cursor]
        choice = SSHActionModal(self.stdscr, host).run()
        if choice is None:
            return
        label, cmd, destructive = choice
        if destructive and not ConfirmDialog(self.stdscr, f"Destructive action: {cmd}. Continue? [y/N]").run():
            return
        self.pending_ssh = label
        self.message = f"running '{label}' on {host.name}..."

        def worker() -> None:
            result = run_ssh_action(host.ssh_user, host.resolved_ssh_host(), cmd, port=host.ssh_port)
            self.ssh_queue.put((label, result))

        threading.Thread(target=worker, daemon=True).start()

    def show_ssh_result(self, label: str, result: SSHResult) -> None:
        lines = [f"Exit code: {result.returncode}", ""]
        if result.timed_out:
            lines.append("Timed out.")
        if result.stdout:
            lines.append("--- stdout ---")
            lines.extend(result.stdout.splitlines())
        if result.stderr:
            lines.append("--- stderr ---")
            lines.extend(result.stderr.splitlines())
        if not result.stdout and not result.stderr and not result.timed_out:
            lines.append("(no output)")
        TextViewer(self.stdscr, lines, title=label).run()

    def show_help(self) -> None:
        lines = [
            "↑/↓ or j/k   move cursor",
            "space        toggle selection",
            "a / A        select all / none",
            "enter / w    wake selected hosts (or the one under the cursor)",
            "n            new host",
            "e            edit host",
            "d            delete selected host(s)",
            "s            SSH actions for the host under the cursor",
            "r            refresh status now",
            "/            filter by name",
            "q / esc      quit (Ctrl-C also quits cleanly)",
        ]
        TextViewer(self.stdscr, lines, title="help").run()


def run(config_path: Optional[Path] = None) -> int:
    def _main(stdscr) -> None:
        App(stdscr, config_path).run()

    try:
        curses.wrapper(_main)
    except KeyboardInterrupt:
        pass
    return 0
