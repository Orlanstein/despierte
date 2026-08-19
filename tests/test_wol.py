import unittest

from despierte.config import InvalidMACError
from despierte.wol import build_magic_packet


class BuildMagicPacketTests(unittest.TestCase):
    def test_known_mac_colon_separated(self):
        packet = build_magic_packet("AA:BB:CC:DD:EE:FF")
        expected = b"\xff" * 6 + bytes.fromhex("AABBCCDDEEFF") * 16
        self.assertEqual(packet, expected)
        self.assertEqual(len(packet), 102)

    def test_accepts_dash_and_no_separator(self):
        colon = build_magic_packet("aa:bb:cc:dd:ee:ff")
        dash = build_magic_packet("aa-bb-cc-dd-ee-ff")
        bare = build_magic_packet("aabbccddeeff")
        self.assertEqual(colon, dash)
        self.assertEqual(colon, bare)

    def test_invalid_mac_raises(self):
        with self.assertRaises(InvalidMACError):
            build_magic_packet("not-a-mac")


if __name__ == "__main__":
    unittest.main()
