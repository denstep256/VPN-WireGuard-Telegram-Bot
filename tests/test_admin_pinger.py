import unittest

from app.admin.admin_commands_pinger import _ping_command


class AdminPingerTests(unittest.TestCase):
    def test_linux_ping_command(self):
        self.assertEqual(
            _ping_command("10.0.0.1", system="Linux"),
            ["ping", "-c", "1", "10.0.0.1"],
        )

    def test_windows_ping_command(self):
        self.assertEqual(
            _ping_command("10.0.0.1", system="Windows"),
            ["ping", "-n", "1", "10.0.0.1"],
        )


if __name__ == "__main__":
    unittest.main()
