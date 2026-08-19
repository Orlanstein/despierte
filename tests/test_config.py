import tempfile
import unittest
from pathlib import Path

from despierte.config import (
    ConfigError,
    Host,
    InvalidIPError,
    InvalidMACError,
    SSHAction,
    find_host,
    load_config,
    normalize_mac,
    save_config,
    validate_ipv4,
)


class ConfigRoundTripTests(unittest.TestCase):
    def test_missing_file_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_config(Path(tmp) / "hosts.json"), [])

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub" / "hosts.json"
            hosts = [
                Host(
                    name="a", mac="AA:BB:CC:DD:EE:FF", ip="10.0.0.1",
                    actions=[SSHAction(label="ping", cmd="uptime")],
                ),
            ]
            save_config(hosts, path)
            self.assertEqual(load_config(path), hosts)

    def test_corrupt_json_raises_config_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hosts.json"
            path.write_text("{not json")
            with self.assertRaises(ConfigError):
                load_config(path)

    def test_find_host(self):
        hosts = [Host(name="a", mac="AA:BB:CC:DD:EE:FF"), Host(name="b", mac="11:22:33:44:55:66")]
        self.assertIs(find_host(hosts, "b"), hosts[1])
        self.assertIsNone(find_host(hosts, "missing"))


class ValidatorTests(unittest.TestCase):
    def test_normalize_mac_variants(self):
        self.assertEqual(normalize_mac("aa:bb:cc:dd:ee:ff"), "AA:BB:CC:DD:EE:FF")
        self.assertEqual(normalize_mac("aabbccddeeff"), "AA:BB:CC:DD:EE:FF")
        self.assertEqual(normalize_mac("aa-bb-cc-dd-ee-ff"), "AA:BB:CC:DD:EE:FF")

    def test_normalize_mac_invalid(self):
        for bad in ("", "zz:zz:zz:zz:zz:zz", "AA:BB:CC:DD:EE", "AA:BB:CC:DD:EE:FF:00"):
            with self.assertRaises(InvalidMACError):
                normalize_mac(bad)

    def test_validate_ipv4(self):
        self.assertEqual(validate_ipv4("192.168.1.1"), "192.168.1.1")
        with self.assertRaises(InvalidIPError):
            validate_ipv4("999.999.999.999")


if __name__ == "__main__":
    unittest.main()
