import subprocess
import unittest

from siliconnet.network_monitor import NetworkMonitor, exception_entry_for_flow

LSOF_COMMAND = ["lsof", "-nP", "+c", "0", "-iTCP", "-iUDP"]

LSOF_OUTPUT = (
    "COMMAND         PID           USER   FD   TYPE             DEVICE SIZE/OFF NODE NAME\n"
    "Discord        1234         tester   55u  IPv4 0x9a1b2c3d4e5f6a7b      0t0  TCP "
    "192.168.1.5:51234->93.184.216.34:443 (ESTABLISHED)\n"
    "Google Chrome  4321         tester   77u  IPv4 0x1122334455667788      0t0  TCP "
    "127.0.0.1:51235->127.0.0.1:8888 (ESTABLISHED)\n"
    "curl            777         tester    4u  IPv6 0xaabbccddeeff0011      0t0  TCP "
    "[fe80::1%en0]:5555->[2606:2800:220:1:248:1893:25c8:1946]:443 (ESTABLISHED)\n"
    "mDNSResponder   999 _mdnsresponder   12u  IPv4 0x5566778899aabbcc      0t0  UDP "
    "192.168.1.5:58000->8.8.8.8:domain\n"
    "python3        1500         tester    9u  IPv4 0x0011223344556677      0t0  TCP "
    "192.168.1.5:51300 (LISTEN)\n"
)


class _Runner:
    def __init__(self, *, returncode=0, stdout=LSOF_OUTPUT, stderr=""):
        self.calls = []
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def __call__(self, args, _timeout):
        self.calls.append(args)
        if args != LSOF_COMMAND:
            raise AssertionError(args)
        return subprocess.CompletedProcess(args, self.returncode, stdout=self.stdout, stderr=self.stderr)


def _monitor(runner=None, **kwargs):
    kwargs.setdefault("system", "Darwin")
    kwargs.setdefault("which", lambda name: f"/usr/sbin/{name}")
    kwargs.setdefault("cache_ttl", 0)
    return NetworkMonitor(runner=runner or _Runner(), **kwargs)


class NetworkMonitorTests(unittest.TestCase):
    def test_macos_snapshot_parses_lsof_and_process_names(self):
        monitor = _monitor()

        snapshot = monitor.snapshot(proxy_bypass=[], always_bypass=["127.*"])

        self.assertTrue(snapshot["supported"])
        self.assertEqual(snapshot["summary"]["flow_count"], 4)
        external = next(flow for flow in snapshot["flows"] if flow["remote_address"] == "93.184.216.34")
        self.assertEqual(external["process_name"], "Discord")
        self.assertEqual(external["pid"], 1234)
        self.assertEqual(external["protocol"], "TCP")
        self.assertEqual(external["local_port"], 51234)
        self.assertEqual(external["remote_port"], 443)
        self.assertEqual(external["state"], "ESTABLISHED")
        self.assertEqual(external["exception_entry"], "93.184.216.34")
        self.assertFalse(external["is_exception"])

    def test_command_names_with_spaces_and_local_bypass_match(self):
        monitor = _monitor()

        snapshot = monitor.snapshot(proxy_bypass=[], always_bypass=["127.*"])

        local = next(flow for flow in snapshot["flows"] if flow["remote_address"] == "127.0.0.1")
        self.assertEqual(local["process_name"], "Google Chrome")
        self.assertEqual(local["pid"], 4321)
        self.assertTrue(local["is_exception"])
        self.assertEqual(local["exception_entry"], "")

    def test_ipv6_zone_is_stripped_and_named_udp_port_resolves(self):
        monitor = _monitor()

        snapshot = monitor.snapshot()

        ipv6 = next(flow for flow in snapshot["flows"] if flow["pid"] == 777)
        self.assertEqual(ipv6["local_address"], "fe80::1")
        self.assertEqual(ipv6["remote_address"], "2606:2800:220:1:248:1893:25c8:1946")
        self.assertEqual(ipv6["remote_port"], 443)
        udp = next(flow for flow in snapshot["flows"] if flow["protocol"] == "UDP")
        self.assertEqual(udp["process_name"], "mDNSResponder")
        self.assertEqual(udp["remote_address"], "8.8.8.8")
        self.assertEqual(udp["remote_port"], 53)
        self.assertEqual(udp["state"], "")

    def test_listening_socket_without_peer_is_skipped(self):
        monitor = _monitor()

        snapshot = monitor.snapshot()

        self.assertNotIn(1500, [flow["pid"] for flow in snapshot["flows"]])

    def test_snapshot_marks_new_proxy_bypass_without_duplicate_parse(self):
        runner = _Runner()
        monitor = _monitor(runner, cache_ttl=60)

        first = monitor.snapshot(proxy_bypass=[], always_bypass=[])
        second = monitor.snapshot(proxy_bypass=["93.184.216.34"], always_bypass=[])

        self.assertFalse(next(flow for flow in first["flows"] if flow["remote_address"] == "93.184.216.34")["is_exception"])
        self.assertTrue(next(flow for flow in second["flows"] if flow["remote_address"] == "93.184.216.34")["is_exception"])
        self.assertEqual(len(runner.calls), 1)

    def test_lsof_exit_code_one_is_treated_as_empty_result(self):
        monitor = _monitor(_Runner(returncode=1, stdout=""))

        snapshot = monitor.snapshot()

        self.assertTrue(snapshot["supported"])
        self.assertEqual(snapshot["flows"], [])
        self.assertEqual(snapshot["error"], "")

    def test_lsof_failure_is_reported_in_snapshot_error(self):
        monitor = _monitor(_Runner(returncode=2, stdout="", stderr="lsof: permission denied"))

        snapshot = monitor.snapshot()

        self.assertTrue(snapshot["supported"])
        self.assertEqual(snapshot["flows"], [])
        self.assertIn("permission denied", snapshot["error"])

    def test_missing_lsof_returns_unsupported_snapshot(self):
        monitor = NetworkMonitor(system="Darwin", which=lambda _name: None)

        snapshot = monitor.snapshot()

        self.assertFalse(snapshot["supported"])
        self.assertEqual(snapshot["flows"], [])
        self.assertEqual(snapshot["summary"]["flow_count"], 0)
        self.assertIn("lsof command", snapshot["error"])

    def test_non_macos_returns_unsupported_snapshot(self):
        monitor = NetworkMonitor(system="Linux", which=lambda name: f"/usr/bin/{name}")

        snapshot = monitor.snapshot()

        self.assertFalse(snapshot["supported"])
        self.assertFalse(monitor.supported())
        self.assertEqual(snapshot["flows"], [])
        self.assertEqual(snapshot["summary"]["flow_count"], 0)
        self.assertIn("macOS", snapshot["error"])

    def test_exception_entry_skips_local_and_empty_remote(self):
        self.assertEqual(exception_entry_for_flow({"remote_address": "127.0.0.1", "remote_port": 80}), "")
        self.assertEqual(exception_entry_for_flow({"remote_address": "*", "remote_port": None}), "")
        self.assertEqual(exception_entry_for_flow({"remote_address": "93.184.216.34", "remote_port": 443}), "93.184.216.34")


if __name__ == "__main__":
    unittest.main()
