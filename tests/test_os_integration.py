import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from siliconnet import os_integration
from siliconnet.os_integration import ProxyBackend

ADMIN_DENIED = "You must be an administrator to change this setting."


class _FakeNetworkSetup:
    """Emulates the ``networksetup``/``launchctl`` command surface used by the port."""

    def __init__(self, services=None, *, deny_writes=False):
        self.services = services or {
            "Wi-Fi": {"web": (False, "", 0), "secure": (False, "", 0), "bypass": ["*.local", "169.254/16"]},
            "Ethernet": {"web": (True, "10.0.0.9", 3128), "secure": (False, "", 0), "bypass": []},
        }
        self.deny_writes = deny_writes
        self.calls = []

    def __call__(self, args, timeout=5.0):
        self.calls.append(list(args))
        tool = args[0]
        if tool == "networksetup":
            return self._networksetup(args)
        if tool in {"launchctl", "defaults", "osascript"}:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        raise AssertionError(args)

    def _networksetup(self, args):
        flag = args[1]
        if flag == "-listallnetworkservices":
            body = "An asterisk (*) denotes that a network service is disabled.\n"
            body += "\n".join(list(self.services) + ["*Bluetooth PAN"]) + "\n"
            return subprocess.CompletedProcess(args, 0, stdout=body, stderr="")

        service = args[2]
        state = self.services[service]
        if flag in {"-getwebproxy", "-getsecurewebproxy"}:
            enabled, server, port = state["web" if flag == "-getwebproxy" else "secure"]
            body = (
                f"Enabled: {'Yes' if enabled else 'No'}\n"
                f"Server: {server}\n"
                f"Port: {port}\n"
                "Authenticated Proxy Enabled: 0\n"
            )
            return subprocess.CompletedProcess(args, 0, stdout=body, stderr="")
        if flag == "-getproxybypassdomains":
            entries = state["bypass"]
            if not entries:
                body = "There aren't any bypass domains set on this network service.\n"
            else:
                body = "\n".join(entries) + "\n"
            return subprocess.CompletedProcess(args, 0, stdout=body, stderr="")

        if self.deny_writes:
            return subprocess.CompletedProcess(args, 1, stdout="", stderr=ADMIN_DENIED)
        return self._apply_write(args, flag, service, state)

    def _apply_write(self, args, flag, service, state):
        if flag in {"-setwebproxy", "-setsecurewebproxy"}:
            key = "web" if flag == "-setwebproxy" else "secure"
            state[key] = (True, args[3], int(args[4]))
        elif flag in {"-setwebproxystate", "-setsecurewebproxystate"}:
            key = "web" if flag == "-setwebproxystate" else "secure"
            enabled = args[3].lower() == "on"
            server, port = state[key][1], state[key][2]
            state[key] = (enabled, server if enabled else "", port if enabled else 0)
        elif flag == "-setproxybypassdomains":
            entries = list(args[3:])
            state["bypass"] = [] if entries == ["Empty"] else entries
        else:
            raise AssertionError(args)
        del service
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    def flags(self):
        return [call[1] for call in self.calls if call[0] == "networksetup"]


class ProxyBackendTests(unittest.TestCase):
    def test_backend_is_supported_when_networksetup_exists(self):
        with patch("siliconnet.os_integration.shutil.which", return_value="/usr/sbin/networksetup"):
            backend = os_integration.detect_proxy_backend()

        self.assertEqual(backend.name, "macos-networksetup")
        self.assertTrue(backend.supported)
        self.assertEqual(backend.error, "")

    def test_backend_is_unsupported_without_networksetup(self):
        with patch("siliconnet.os_integration.shutil.which", return_value=None):
            backend = os_integration.detect_proxy_backend()

        self.assertFalse(backend.supported)
        self.assertIn("networksetup", backend.error)

    def test_bypass_list_maps_local_token_and_drops_duplicates(self):
        result = os_integration.build_bypass_list(
            ["<local>", "localhost", "127.0.0.1"],
            ["*.example.com", "localhost"],
        )

        self.assertEqual(result, "*.local,localhost,127.0.0.1,*.example.com")

    def test_is_app_proxy_server_compares_host_and_port(self):
        self.assertTrue(os_integration.is_app_proxy_server("127.0.0.1:8080", "127.0.0.1", 8080))
        self.assertFalse(os_integration.is_app_proxy_server("127.0.0.1:9999", "127.0.0.1", 8080))
        self.assertFalse(os_integration.is_app_proxy_server(None, "127.0.0.1", 8080))

    def test_list_network_services_skips_disabled_entries_and_legend(self):
        fake = _FakeNetworkSetup()
        with patch("siliconnet.os_integration._run", fake):
            services = os_integration.list_network_services()

        self.assertEqual(services, ["Wi-Fi", "Ethernet"])


class SystemProxyTests(unittest.TestCase):
    def test_enable_backs_up_state_and_points_every_service_at_siliconnet(self):
        fake = _FakeNetworkSetup()
        with tempfile.TemporaryDirectory() as data_tmp:
            with patch("siliconnet.os_integration.shutil.which", return_value="/usr/sbin/networksetup"), patch(
                "siliconnet.os_integration._run", fake
            ):
                self.assertTrue(
                    os_integration.set_system_proxy(
                        True, "127.0.0.1", 8080, ["<local>"], ["*.example.com"], data_tmp
                    )
                )

            backup_path = os.path.join(data_tmp, "macos_proxy_state.json")
            self.assertTrue(os.path.exists(backup_path))
            with open(backup_path, "r", encoding="utf-8") as f:
                backup = json.load(f)

        self.assertEqual(backup["backend"], "macos-networksetup")
        self.assertEqual(backup["state"]["services"]["Ethernet"]["web"]["server"], "10.0.0.9")
        self.assertEqual(backup["state"]["services"]["Ethernet"]["web"]["port"], 3128)
        for service in ("Wi-Fi", "Ethernet"):
            self.assertEqual(fake.services[service]["web"], (True, "127.0.0.1", 8080))
            self.assertEqual(fake.services[service]["secure"], (True, "127.0.0.1", 8080))
            self.assertEqual(fake.services[service]["bypass"], ["*.local", "*.example.com"])

    def test_disable_restores_the_backed_up_state_and_clears_the_backup(self):
        fake = _FakeNetworkSetup()
        original = {name: dict(state) for name, state in fake.services.items()}
        with tempfile.TemporaryDirectory() as data_tmp:
            with patch("siliconnet.os_integration.shutil.which", return_value="/usr/sbin/networksetup"), patch(
                "siliconnet.os_integration._run", fake
            ):
                os_integration.set_system_proxy(True, "127.0.0.1", 8080, ["<local>"], [], data_tmp)
                self.assertTrue(os_integration.set_system_proxy(False, "127.0.0.1", 8080, [], [], data_tmp))

            self.assertFalse(os.path.exists(os.path.join(data_tmp, "macos_proxy_state.json")))

        self.assertEqual(fake.services["Wi-Fi"]["web"], original["Wi-Fi"]["web"])
        self.assertEqual(fake.services["Ethernet"]["web"], original["Ethernet"]["web"])
        self.assertEqual(fake.services["Wi-Fi"]["bypass"], ["*.local", "169.254/16"])

    def test_disable_without_backup_only_clears_siliconnet_owned_services(self):
        fake = _FakeNetworkSetup(
            {
                "Wi-Fi": {"web": (True, "127.0.0.1", 8080), "secure": (True, "127.0.0.1", 8080), "bypass": ["*.local"]},
                "Ethernet": {"web": (True, "10.0.0.9", 3128), "secure": (False, "", 0), "bypass": []},
            }
        )
        with tempfile.TemporaryDirectory() as data_tmp:
            with patch("siliconnet.os_integration.shutil.which", return_value="/usr/sbin/networksetup"), patch(
                "siliconnet.os_integration._run", fake
            ):
                self.assertTrue(os_integration.set_system_proxy(False, "127.0.0.1", 8080, [], [], data_tmp))

        self.assertEqual(fake.services["Wi-Fi"]["web"], (False, "", 0))
        self.assertEqual(fake.services["Wi-Fi"]["secure"], (False, "", 0))
        self.assertEqual(fake.services["Ethernet"]["web"], (True, "10.0.0.9", 3128))

    def test_admin_denied_write_is_replayed_through_osascript(self):
        fake = _FakeNetworkSetup(deny_writes=True)
        with tempfile.TemporaryDirectory() as data_tmp:
            with patch("siliconnet.os_integration.shutil.which", return_value="/usr/sbin/networksetup"), patch(
                "siliconnet.os_integration._run", fake
            ):
                self.assertTrue(
                    os_integration.set_system_proxy(True, "127.0.0.1", 8080, [], [], data_tmp)
                )

        osascript_calls = [call for call in fake.calls if call[0] == "osascript"]
        self.assertEqual(len(osascript_calls), 1)
        script = osascript_calls[0][2]
        self.assertIn("with administrator privileges", script)
        self.assertIn("networksetup -setsecurewebproxy", script)

    def test_cancelled_admin_prompt_reports_failure(self):
        fake = _FakeNetworkSetup(deny_writes=True)

        def run(args, timeout=5.0):
            if args[0] == "osascript":
                return subprocess.CompletedProcess(args, 1, stdout="", stderr="User canceled. (-128)")
            return fake(args, timeout)

        with tempfile.TemporaryDirectory() as data_tmp:
            with patch("siliconnet.os_integration.shutil.which", return_value="/usr/sbin/networksetup"), patch(
                "siliconnet.os_integration._run", run
            ):
                self.assertFalse(os_integration.set_system_proxy(True, "127.0.0.1", 8080, [], [], data_tmp))

    def test_set_system_proxy_returns_false_when_backend_write_fails(self):
        with tempfile.TemporaryDirectory() as data_tmp:
            with (
                patch("siliconnet.os_integration.detect_proxy_backend", return_value=ProxyBackend("macos-networksetup", True)),
                patch("siliconnet.os_integration._read_backend_state", return_value={"services": {}}),
                patch("siliconnet.os_integration._enable_backend_proxy", side_effect=RuntimeError("boom")),
            ):
                self.assertFalse(os_integration.set_system_proxy(True, "127.0.0.1", 8080, [], [], data_tmp))

    def test_set_system_proxy_is_unsupported_without_networksetup(self):
        with tempfile.TemporaryDirectory() as data_tmp:
            with patch("siliconnet.os_integration.shutil.which", return_value=None):
                self.assertFalse(os_integration.set_system_proxy(True, "127.0.0.1", 8080, [], [], data_tmp))

    def test_summary_reports_ownership_backup_and_managed_services(self):
        fake = _FakeNetworkSetup()
        with tempfile.TemporaryDirectory() as data_tmp:
            with patch("siliconnet.os_integration.shutil.which", return_value="/usr/sbin/networksetup"), patch(
                "siliconnet.os_integration._run", fake
            ):
                os_integration.set_system_proxy(True, "127.0.0.1", 8080, ["<local>"], [], data_tmp)
                summary = os_integration.get_proxy_summary(data_tmp, "127.0.0.1", 8080)

        self.assertEqual(summary["backend"], "macos-networksetup")
        self.assertTrue(summary["supported"])
        self.assertTrue(summary["enabled"])
        self.assertTrue(summary["owned_by_siliconnet"])
        self.assertEqual(summary["server"], "127.0.0.1:8080")
        self.assertEqual(summary["services"], ["Ethernet", "Wi-Fi"])
        self.assertTrue(summary["backup"]["exists"])

    def test_ensure_system_proxy_enabled_is_a_no_op_when_already_owned(self):
        fake = _FakeNetworkSetup()
        with tempfile.TemporaryDirectory() as data_tmp:
            with patch("siliconnet.os_integration.shutil.which", return_value="/usr/sbin/networksetup"), patch(
                "siliconnet.os_integration._run", fake
            ):
                os_integration.set_system_proxy(True, "127.0.0.1", 8080, [], [], data_tmp)
                before = len(fake.calls)
                self.assertTrue(
                    os_integration.ensure_system_proxy_enabled("127.0.0.1", 8080, [], [], data_tmp)
                )
                after = fake.flags()[before:]

        self.assertNotIn("-setwebproxy", after)

    def test_recover_orphaned_proxy_restores_when_a_backup_is_left_behind(self):
        fake = _FakeNetworkSetup()
        with tempfile.TemporaryDirectory() as data_tmp:
            with patch("siliconnet.os_integration.shutil.which", return_value="/usr/sbin/networksetup"), patch(
                "siliconnet.os_integration._run", fake
            ):
                os_integration.set_system_proxy(True, "127.0.0.1", 8080, [], [], data_tmp)
                self.assertTrue(os_integration.recover_orphaned_proxy("127.0.0.1", 8080, data_tmp))

            self.assertFalse(os.path.exists(os.path.join(data_tmp, "macos_proxy_state.json")))

        self.assertEqual(fake.services["Ethernet"]["web"], (True, "10.0.0.9", 3128))

    def test_recover_orphaned_proxy_does_nothing_when_siliconnet_owns_nothing(self):
        fake = _FakeNetworkSetup()
        with tempfile.TemporaryDirectory() as data_tmp:
            with patch("siliconnet.os_integration.shutil.which", return_value="/usr/sbin/networksetup"), patch(
                "siliconnet.os_integration._run", fake
            ):
                self.assertFalse(os_integration.recover_orphaned_proxy("127.0.0.1", 8080, data_tmp))


class AutostartTests(unittest.TestCase):
    def test_launch_agent_is_written_loaded_and_removed(self):
        fake = _FakeNetworkSetup()
        with tempfile.TemporaryDirectory() as home_tmp:
            with patch("siliconnet.os_integration.os.path.expanduser", return_value=home_tmp), patch(
                "siliconnet.os_integration._run", fake
            ):
                self.assertFalse(os_integration.get_autostart("SiliconNetDPIBypass"))
                self.assertTrue(
                    os_integration.set_autostart(
                        True,
                        "SiliconNetDPIBypass",
                        "/Applications/SiliconNet/siliconnet/__main__.py",
                        executable="/usr/local/bin/python3",
                    )
                )
                self.assertTrue(os_integration.get_autostart("SiliconNetDPIBypass"))

                plist_path = os.path.join(
                    home_tmp, "Library", "LaunchAgents", "com.siliconnet.SiliconNetDPIBypass.plist"
                )
                with open(plist_path, "r", encoding="utf-8") as f:
                    plist = f.read()

                self.assertIn("<string>/usr/local/bin/python3</string>", plist)
                self.assertIn("<string>siliconnet</string>", plist)
                source_dir = os.path.abspath("/Applications/SiliconNet")
                self.assertIn(f"<key>WorkingDirectory</key><string>{source_dir}</string>", plist)
                self.assertIn("com.siliconnet.SiliconNetDPIBypass", plist)

                self.assertTrue(
                    os_integration.set_autostart(False, "SiliconNetDPIBypass", "/Applications/SiliconNet/siliconnet/__main__.py")
                )
                self.assertFalse(os.path.exists(plist_path))

        self.assertTrue(any(call[0] == "launchctl" for call in fake.calls))

    def test_set_autostart_reports_failure_when_launchctl_rejects_the_agent(self):
        def run(args, timeout=5.0):
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="Load failed: 5: Input/output error")

        with tempfile.TemporaryDirectory() as home_tmp:
            with patch("siliconnet.os_integration.os.path.expanduser", return_value=home_tmp), patch(
                "siliconnet.os_integration._run", run
            ):
                self.assertFalse(
                    os_integration.set_autostart(True, "SiliconNetDPIBypass", "/Applications/SiliconNet/siliconnet/__main__.py")
                )


class UserLanguageTests(unittest.TestCase):
    def test_apple_locale_is_reduced_to_a_supported_language(self):
        def run(args, timeout=5.0):
            self.assertEqual(args, ["defaults", "read", "-g", "AppleLocale"])
            return subprocess.CompletedProcess(args, 0, stdout="tr_TR@calendar=gregorian\n", stderr="")

        with patch("siliconnet.os_integration._run", run):
            self.assertEqual(os_integration.get_user_language(), "tr")

    def test_unsupported_locale_falls_back_to_english(self):
        def run(args, timeout=5.0):
            return subprocess.CompletedProcess(args, 0, stdout="fr_FR\n", stderr="")

        with patch("siliconnet.os_integration._run", run):
            self.assertEqual(os_integration.get_user_language(), "en")

    def test_missing_defaults_command_uses_the_lang_environment_variable(self):
        def run(args, timeout=5.0):
            raise FileNotFoundError("defaults")

        with patch("siliconnet.os_integration._run", run), patch.dict(os.environ, {"LANG": "de_DE.UTF-8"}, clear=True):
            self.assertEqual(os_integration.get_user_language(), "de")


if __name__ == "__main__":
    unittest.main()
