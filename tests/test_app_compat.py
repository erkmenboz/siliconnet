import subprocess
import tempfile
import unittest
from unittest.mock import patch

from siliconnet import app_compat
from tests.test_os_integration import _FakeNetworkSetup


class _FakeLaunchctl:
    """Emulates the ``launchctl getenv/setenv/unsetenv`` surface."""

    def __init__(self, initial=None, fail=False):
        self.env = dict(initial or {})
        self.fail = fail
        self.calls = []

    def __call__(self, args, timeout=5.0):
        self.calls.append(list(args))
        if self.fail:
            return subprocess.CompletedProcess(["launchctl", *args], 1, stdout="", stderr="boom")
        action = args[0]
        name = args[1]
        if action == "getenv":
            value = self.env.get(name)
            if value is None:
                return subprocess.CompletedProcess(["launchctl", *args], 1, stdout="", stderr="")
            return subprocess.CompletedProcess(["launchctl", *args], 0, stdout=f"{value}\n", stderr="")
        if action == "setenv":
            self.env[name] = args[2]
            return subprocess.CompletedProcess(["launchctl", *args], 0, stdout="", stderr="")
        if action == "unsetenv":
            self.env.pop(name, None)
            return subprocess.CompletedProcess(["launchctl", *args], 0, stdout="", stderr="")
        raise AssertionError(args)

    def setenv_calls(self):
        return [c for c in self.calls if c[0] == "setenv"]

    def unsetenv_calls(self):
        return [c for c in self.calls if c[0] == "unsetenv"]


class ProxyEnvValueTests(unittest.TestCase):
    def test_value_format(self):
        self.assertEqual(app_compat.proxy_env_value("127.0.0.1", 8080), "http://127.0.0.1:8080")

    def test_looks_like_ours(self):
        self.assertTrue(app_compat._looks_like_ours("http://127.0.0.1:8080"))
        self.assertTrue(app_compat._looks_like_ours("http://localhost:8080"))
        self.assertFalse(app_compat._looks_like_ours("http://proxy.corp.example:3128"))
        self.assertFalse(app_compat._looks_like_ours(""))


class EnsureProxyEnvTests(unittest.TestCase):
    def test_publishes_all_vars_when_missing(self):
        fake = _FakeLaunchctl()
        with patch.object(app_compat, "_launchctl", fake):
            self.assertTrue(app_compat.ensure_proxy_env("127.0.0.1", 8080))
        for name in app_compat.ENV_PROXY_VARS:
            self.assertEqual(fake.env.get(name), "http://127.0.0.1:8080")
        for name in app_compat.ENV_BYPASS_VARS:
            self.assertEqual(fake.env.get(name), app_compat.ENV_BYPASS_VALUE)

    def test_noop_when_already_published(self):
        initial = {name: "http://127.0.0.1:8080" for name in app_compat.ENV_PROXY_VARS}
        initial.update({name: app_compat.ENV_BYPASS_VALUE for name in app_compat.ENV_BYPASS_VARS})
        fake = _FakeLaunchctl(initial)
        with patch.object(app_compat, "_launchctl", fake):
            self.assertTrue(app_compat.ensure_proxy_env("127.0.0.1", 8080))
        self.assertEqual(fake.setenv_calls(), [])

    def test_republishes_stale_values(self):
        fake = _FakeLaunchctl({"HTTPS_PROXY": "http://127.0.0.1:9999"})
        with patch.object(app_compat, "_launchctl", fake):
            self.assertTrue(app_compat.ensure_proxy_env("127.0.0.1", 8080))
        self.assertEqual(fake.env["HTTPS_PROXY"], "http://127.0.0.1:8080")
        self.assertEqual(fake.env["http_proxy"], "http://127.0.0.1:8080")

    def test_failure_returns_false_without_raising(self):
        fake = _FakeLaunchctl(fail=True)
        with patch.object(app_compat, "_launchctl", fake):
            self.assertFalse(app_compat.ensure_proxy_env("127.0.0.1", 8080))


class RemoveProxyEnvTests(unittest.TestCase):
    def test_removes_only_siliconnet_owned_values(self):
        initial = {name: "http://127.0.0.1:8080" for name in app_compat.ENV_PROXY_VARS}
        initial.update({name: app_compat.ENV_BYPASS_VALUE for name in app_compat.ENV_BYPASS_VARS})
        initial["all_proxy"] = "http://proxy.corp.example:3128"  # foreign value must survive
        fake = _FakeLaunchctl(initial)
        with patch.object(app_compat, "_launchctl", fake):
            self.assertTrue(app_compat.remove_proxy_env())
        for name in app_compat.ENV_PROXY_VARS:
            if name == "all_proxy":
                self.assertEqual(fake.env.get(name), "http://proxy.corp.example:3128")
            else:
                self.assertIsNone(fake.env.get(name))
        for name in app_compat.ENV_BYPASS_VARS:
            self.assertIsNone(fake.env.get(name))

    def test_noop_when_nothing_published(self):
        fake = _FakeLaunchctl()
        with patch.object(app_compat, "_launchctl", fake):
            self.assertTrue(app_compat.remove_proxy_env())
        self.assertEqual(fake.unsetenv_calls(), [])

    def test_unreadable_env_is_a_safe_noop(self):
        # If launchctl getenv fails we cannot tell our values from foreign ones,
        # so removal must back off rather than clobber anything blindly.
        fake = _FakeLaunchctl({"HTTPS_PROXY": "http://127.0.0.1:8080"}, fail=True)
        with patch.object(app_compat, "_launchctl", fake):
            self.assertTrue(app_compat.remove_proxy_env())
        self.assertEqual(fake.unsetenv_calls(), [])

    def test_unsetenv_failure_returns_false(self):
        class FlakyUnset(_FakeLaunchctl):
            def __call__(self, args, timeout=5.0):
                if args[0] == "unsetenv":
                    return subprocess.CompletedProcess(["launchctl", *args], 1, stdout="", stderr="boom")
                return super().__call__(args, timeout)

        fake = FlakyUnset({name: "http://127.0.0.1:8080" for name in app_compat.ENV_PROXY_VARS})
        with patch.object(app_compat, "_launchctl", fake):
            self.assertFalse(app_compat.remove_proxy_env())


class OsIntegrationWiringTests(unittest.TestCase):
    def test_enable_publishes_env_and_disable_removes_it(self):
        from siliconnet import os_integration

        with tempfile.TemporaryDirectory() as tmp:
            fake_net = _FakeNetworkSetup()
            fake_ctl = _FakeLaunchctl()
            with patch.object(os_integration, "_run", fake_net), \
                 patch.object(app_compat, "_launchctl", fake_ctl):
                self.assertTrue(os_integration.set_system_proxy(True, "127.0.0.1", 8080, ["<local>"], [], tmp))
                self.assertEqual(fake_ctl.env.get("HTTPS_PROXY"), "http://127.0.0.1:8080")
                self.assertTrue(os_integration.set_system_proxy(False, "127.0.0.1", 8080, [], [], tmp))
                self.assertIsNone(fake_ctl.env.get("HTTPS_PROXY"))

    def test_publish_env_can_be_disabled(self):
        from siliconnet import os_integration

        with tempfile.TemporaryDirectory() as tmp:
            fake_net = _FakeNetworkSetup()
            fake_ctl = _FakeLaunchctl()
            with patch.object(os_integration, "_run", fake_net), \
                 patch.object(app_compat, "_launchctl", fake_ctl):
                self.assertTrue(
                    os_integration.set_system_proxy(
                        True, "127.0.0.1", 8080, ["<local>"], [], tmp, publish_env=False
                    )
                )
                self.assertEqual(fake_ctl.env, {})

    def test_ensure_republishes_when_proxy_already_owned(self):
        from siliconnet import os_integration

        owned = {
            "Wi-Fi": {
                "web": (True, "127.0.0.1", 8080),
                "secure": (True, "127.0.0.1", 8080),
                "bypass": [],
            }
        }
        fake_net = _FakeNetworkSetup(owned)
        fake_ctl = _FakeLaunchctl()
        with patch.object(os_integration, "_run", fake_net), \
             patch.object(app_compat, "_launchctl", fake_ctl):
            self.assertTrue(os_integration.ensure_system_proxy_enabled("127.0.0.1", 8080, [], []))
        self.assertEqual(fake_ctl.env.get("HTTPS_PROXY"), "http://127.0.0.1:8080")

    def test_env_failure_does_not_flip_proxy_result(self):
        from siliconnet import os_integration

        with tempfile.TemporaryDirectory() as tmp:
            fake_net = _FakeNetworkSetup()
            fake_ctl = _FakeLaunchctl(fail=True)
            with patch.object(os_integration, "_run", fake_net), \
                 patch.object(app_compat, "_launchctl", fake_ctl):
                self.assertTrue(os_integration.set_system_proxy(True, "127.0.0.1", 8080, [], [], tmp))


if __name__ == "__main__":
    unittest.main()
