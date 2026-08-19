import subprocess
import unittest
from unittest import mock

from despierte import status


class PingHostTests(unittest.TestCase):
    def test_empty_ip_is_offline(self):
        self.assertFalse(status.ping_host(""))

    @mock.patch("despierte.status.subprocess.run")
    def test_returncode_zero_is_online(self, run):
        run.return_value = mock.Mock(returncode=0)
        self.assertTrue(status.ping_host("10.0.0.1"))

    @mock.patch("despierte.status.subprocess.run")
    def test_returncode_nonzero_is_offline(self, run):
        run.return_value = mock.Mock(returncode=1)
        self.assertFalse(status.ping_host("10.0.0.1"))

    @mock.patch(
        "despierte.status.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="ping", timeout=1),
    )
    def test_timeout_is_offline(self, run):
        self.assertFalse(status.ping_host("10.0.0.1"))


class StatusMonitorCycleTests(unittest.TestCase):
    @mock.patch("despierte.status.ping_host")
    def test_run_cycle_updates_results(self, ping_host):
        ping_host.side_effect = lambda ip, timeout=1.0: ip == "10.0.0.1"
        monitor = status.StatusMonitor(lambda: {"up": "10.0.0.1", "down": "10.0.0.2"})
        monitor._run_cycle()
        snapshot = monitor.snapshot()
        self.assertEqual(snapshot["up"].status, status.Status.ONLINE)
        self.assertEqual(snapshot["down"].status, status.Status.OFFLINE)

    def test_run_cycle_records_error_without_raising(self):
        def boom():
            raise RuntimeError("no targets")

        monitor = status.StatusMonitor(boom)
        monitor._run_cycle()
        self.assertIsNotNone(monitor.last_error())


if __name__ == "__main__":
    unittest.main()
