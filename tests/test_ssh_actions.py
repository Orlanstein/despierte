import subprocess
import unittest
from unittest import mock

from despierte.ssh_actions import run_ssh_action


class RunSSHActionTests(unittest.TestCase):
    @mock.patch("despierte.ssh_actions.subprocess.run")
    def test_builds_expected_argv(self, run):
        run.return_value = mock.Mock(returncode=0, stdout="ok\n", stderr="")
        result = run_ssh_action("orlando", "10.0.0.5", "uptime", port=2222)
        run.assert_called_once_with(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-p", "2222", "orlando@10.0.0.5", "uptime"],
            capture_output=True, text=True, timeout=30.0,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "ok\n")

    @mock.patch("despierte.ssh_actions.subprocess.run")
    def test_no_user_omits_at_sign(self, run):
        run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
        run_ssh_action("", "10.0.0.5", "uptime")
        argv = run.call_args[0][0]
        self.assertIn("10.0.0.5", argv)
        self.assertNotIn("@10.0.0.5", argv)

    @mock.patch(
        "despierte.ssh_actions.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="ssh", timeout=30),
    )
    def test_timeout_is_reported(self, run):
        result = run_ssh_action("orlando", "10.0.0.5", "uptime")
        self.assertTrue(result.timed_out)
        self.assertEqual(result.returncode, -1)


if __name__ == "__main__":
    unittest.main()
