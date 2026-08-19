import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from despierte import cli


class CLITests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.config_path = Path(self._tmp.name) / "hosts.json"

    def _run(self, args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(["--config", str(self.config_path), *args])
        return code, buf.getvalue()

    def test_add_then_list_json(self):
        code, _ = self._run(["add", "--name", "pc", "--mac", "aa:bb:cc:dd:ee:ff", "--ip", "10.0.0.5"])
        self.assertEqual(code, 0)
        code, out = self._run(["list", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data[0]["name"], "pc")
        self.assertEqual(data[0]["mac"], "AA:BB:CC:DD:EE:FF")

    def test_add_duplicate_name_fails(self):
        self._run(["add", "--name", "pc", "--mac", "aa:bb:cc:dd:ee:ff"])
        code, _ = self._run(["add", "--name", "pc", "--mac", "11:22:33:44:55:66"])
        self.assertEqual(code, 1)

    def test_wake_unknown_host(self):
        code, _ = self._run(["wake", "nope"])
        self.assertEqual(code, 2)

    @mock.patch("despierte.cli.send_magic_packet")
    def test_wake_known_host(self, send):
        self._run(["add", "--name", "pc", "--mac", "aa:bb:cc:dd:ee:ff", "--ip", "10.0.0.5"])
        code, _ = self._run(["wake", "pc"])
        self.assertEqual(code, 0)
        send.assert_called_once()

    @mock.patch("despierte.cli.ping_host", return_value=True)
    def test_status_online_exit_code(self, ping_host):
        self._run(["add", "--name", "pc", "--mac", "aa:bb:cc:dd:ee:ff", "--ip", "10.0.0.5"])
        code, out = self._run(["status", "pc"])
        self.assertEqual(code, 0)
        self.assertIn("online", out)

    @mock.patch("despierte.cli.ping_host", return_value=False)
    def test_status_offline_exit_code(self, ping_host):
        self._run(["add", "--name", "pc", "--mac", "aa:bb:cc:dd:ee:ff", "--ip", "10.0.0.5"])
        code, _ = self._run(["status", "pc"])
        self.assertEqual(code, 1)

    def test_rm_requires_confirmation_without_yes(self):
        self._run(["add", "--name", "pc", "--mac", "aa:bb:cc:dd:ee:ff"])
        with mock.patch("builtins.input", return_value="n"):
            code, _ = self._run(["rm", "pc"])
        self.assertEqual(code, 1)
        _, out = self._run(["list", "--json"])
        self.assertEqual(len(json.loads(out)), 1)

    def test_rm_with_yes_flag(self):
        self._run(["add", "--name", "pc", "--mac", "aa:bb:cc:dd:ee:ff"])
        code, _ = self._run(["rm", "pc", "--yes"])
        self.assertEqual(code, 0)
        _, out = self._run(["list", "--json"])
        self.assertEqual(json.loads(out), [])

    def test_run_unknown_action(self):
        self._run(["add", "--name", "pc", "--mac", "aa:bb:cc:dd:ee:ff", "--ip", "10.0.0.5"])
        code, _ = self._run(["run", "pc", "no-existe"])
        self.assertEqual(code, 2)

    @mock.patch("despierte.cli.run_ssh_action")
    def test_run_custom_cmd(self, run_ssh_action):
        run_ssh_action.return_value = mock.Mock(returncode=0, stdout="ok\n", stderr="", timed_out=False)
        self._run(["add", "--name", "pc", "--mac", "aa:bb:cc:dd:ee:ff", "--ip", "10.0.0.5"])
        code, out = self._run(["run", "pc", "--cmd", "uptime", "--yes"])
        self.assertEqual(code, 0)
        self.assertIn("ok", out)


if __name__ == "__main__":
    unittest.main()
