import os
from pathlib import Path
import subprocess
import types
import unittest
from unittest.mock import patch

from siliconnet.tray import (
    DNS_FLUSH_COMMAND,
    MDNS_RELOAD_COMMAND,
    TrayManager,
    TrayRuntimeContext,
    build_confirm_script,
    build_full_shutdown_prompt,
    build_status_title,
    confirm_dialog,
    escape_applescript,
    status_bar_icon_class,
)

try:
    from PIL import Image
except ImportError:
    Image = None

ASSETS = Path(__file__).resolve().parents[1] / "assets"


class _Logger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def error(self, message):
        self.messages.append(("error", message))

    def warning(self, message):
        self.messages.append(("warning", message))


class _Loop:
    def __init__(self):
        self.calls = []

    def call_soon_threadsafe(self, callback):
        self.calls.append(callback)
        callback()


class _Event:
    def __init__(self):
        self.set_count = 0

    def set(self):
        self.set_count += 1


class _Icon:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


async def _resolve_bypass_ips():
    return None


def _build_manager():
    state = {"running": True, "saved": 0, "proxy": [], "released": 0}
    loop = _Loop()
    event = _Event()
    logger = _Logger()
    manager = TrayManager(
        TrayRuntimeContext(
            version="9.9.9",
            logger=logger,
            local_host="127.0.0.1",
            web_port=8888,
            log_file="missing.log",
            app_file="/Applications/SiliconNet/siliconnet/__main__.py",
            python_executable="python3",
            get_status=lambda: "running",
            get_ping_ms=lambda: 42,
            get_loop=lambda: loop,
            get_shutdown_event=lambda: event,
            set_running=lambda value: state.__setitem__("running", value),
            force_save=lambda: state.__setitem__("saved", state["saved"] + 1),
            set_proxy_enabled=lambda value: state["proxy"].append(value),
            release_instance_lock=lambda: state.__setitem__("released", state["released"] + 1),
            resolve_bypass_ips=_resolve_bypass_ips,
        )
    )
    return manager, state, loop, event, logger


class TrayTextTests(unittest.TestCase):
    def test_status_title_and_prompt_text(self):
        self.assertEqual(build_status_title("running", 42), "SiliconNet - Active | 42ms")
        self.assertEqual(build_status_title("stopped", -1), "SiliconNet - Stopped")
        self.assertIn("Tam Kapatma", build_full_shutdown_prompt("tr")[0])
        self.assertIn("Vollstaendiges", build_full_shutdown_prompt("de")[0])
        self.assertIn("Full Shutdown", build_full_shutdown_prompt("en")[0])

    def test_every_prompt_describes_the_macos_dns_flush(self):
        for lang in ("tr", "de", "en"):
            self.assertIn("dscacheutil -flushcache", build_full_shutdown_prompt(lang)[1])

    def test_applescript_escaping_covers_quotes_backslashes_and_newlines(self):
        self.assertEqual(escape_applescript('a "b" c'), 'a \\"b\\" c')
        self.assertEqual(escape_applescript("a\\b"), "a\\\\b")
        self.assertEqual(escape_applescript("line1\nline2"), "line1\\nline2")

    def test_confirm_script_carries_title_message_and_buttons(self):
        script = build_confirm_script('Title "X"', "line1\nline2", ("Cancel", "Continue"))

        self.assertIn('display dialog "line1\\nline2"', script)
        self.assertIn('with title "Title \\"X\\""', script)
        self.assertIn('buttons {"Cancel", "Continue"}', script)
        self.assertIn('default button "Continue"', script)


class ConfirmDialogTests(unittest.TestCase):
    def test_ok_button_confirms(self):
        with patch("siliconnet.tray.subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertTrue(confirm_dialog("Title", "Message", "en"))

        self.assertEqual(run.call_args.args[0][0], "osascript")

    def test_cancel_button_declines(self):
        with patch("siliconnet.tray.subprocess.run", return_value=subprocess.CompletedProcess([], 1)):
            self.assertFalse(confirm_dialog("Title", "Message", "en"))

    def test_missing_osascript_falls_through_with_a_warning(self):
        logger = _Logger()
        with patch("siliconnet.tray.subprocess.run", side_effect=FileNotFoundError("osascript")):
            self.assertTrue(confirm_dialog("Title", "Message", "en", logger))

        self.assertEqual(logger.messages[0][0], "warning")


class TrayActionTests(unittest.TestCase):
    def test_exit_saves_state_clears_proxy_and_signals_shutdown(self):
        manager, state, loop, event, logger = _build_manager()
        icon = _Icon()

        manager.exit(icon)

        self.assertFalse(state["running"])
        self.assertEqual(state["saved"], 1)
        self.assertEqual(state["proxy"], [False])
        self.assertEqual(len(loop.calls), 1)
        self.assertEqual(event.set_count, 1)
        self.assertTrue(icon.stopped)
        self.assertIn(("info", "User exit"), logger.messages)

    def test_restart_releases_lock_and_spawns_delayed_process(self):
        manager, state, _loop, event, _logger = _build_manager()
        icon = _Icon()

        with patch("siliconnet.tray.subprocess.Popen") as popen:
            manager.restart(icon)

        self.assertFalse(state["running"])
        self.assertEqual(state["released"], 1)
        self.assertEqual(event.set_count, 1)
        self.assertTrue(icon.stopped)
        popen.assert_called_once()
        self.assertIn("'-m', 'siliconnet'", popen.call_args.args[0][2])
        source_dir = os.path.abspath("/Applications/SiliconNet")
        self.assertIn(f"cwd={source_dir!r}", popen.call_args.args[0][2])

    def test_open_log_uses_the_macos_open_command_when_the_file_exists(self):
        manager, _state, _loop, _event, _logger = _build_manager()

        with patch("siliconnet.tray.os.path.exists", return_value=True), patch("siliconnet.tray.subprocess.Popen") as popen:
            manager.open_log()

        popen.assert_called_once_with(["open", "-t", "missing.log"])

    def test_open_log_is_skipped_when_the_log_file_is_absent(self):
        manager, _state, _loop, _event, _logger = _build_manager()

        with patch("siliconnet.tray.os.path.exists", return_value=False), patch("siliconnet.tray.subprocess.Popen") as popen:
            manager.open_log()

        popen.assert_not_called()

    def test_open_dashboard_uses_the_configured_host_and_port(self):
        manager, _state, _loop, _event, _logger = _build_manager()

        with patch("siliconnet.tray.webbrowser.open") as browser:
            manager.open_dashboard()

        browser.assert_called_once_with("http://127.0.0.1:8888")


class FullShutdownTests(unittest.TestCase):
    def test_confirmed_shutdown_clears_proxy_and_flushes_dns(self):
        manager, state, _loop, event, logger = _build_manager()
        icon = _Icon()

        with (
            patch("siliconnet.tray.get_user_language", return_value="en"),
            patch("siliconnet.tray.confirm_dialog", return_value=True),
            patch("siliconnet.tray.subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as run,
        ):
            manager._run_full_shutdown(icon)

        self.assertFalse(state["running"])
        self.assertEqual(state["proxy"], [False])
        self.assertEqual(event.set_count, 1)
        self.assertTrue(icon.stopped)
        self.assertEqual([call.args[0] for call in run.call_args_list], [DNS_FLUSH_COMMAND, MDNS_RELOAD_COMMAND])
        self.assertIn(("info", "Full shutdown initiated on macOS"), logger.messages)

    def test_declined_shutdown_leaves_the_proxy_alone(self):
        manager, state, _loop, event, _logger = _build_manager()
        icon = _Icon()

        with (
            patch("siliconnet.tray.get_user_language", return_value="tr"),
            patch("siliconnet.tray.confirm_dialog", return_value=False),
            patch("siliconnet.tray.subprocess.run") as run,
        ):
            manager._run_full_shutdown(icon)

        self.assertTrue(state["running"])
        self.assertEqual(state["proxy"], [])
        self.assertEqual(event.set_count, 0)
        self.assertFalse(icon.stopped)
        run.assert_not_called()

    def test_missing_dscacheutil_is_reported_without_stopping_the_shutdown(self):
        manager, _state, _loop, _event, logger = _build_manager()
        icon = _Icon()

        with (
            patch("siliconnet.tray.get_user_language", return_value="en"),
            patch("siliconnet.tray.confirm_dialog", return_value=True),
            patch("siliconnet.tray.subprocess.run", side_effect=FileNotFoundError("dscacheutil")),
        ):
            manager._run_full_shutdown(icon)

        self.assertTrue(icon.stopped)
        self.assertTrue(any(level == "warning" for level, _ in logger.messages))


@unittest.skipUnless(Image is not None, "Pillow is required for icon asset checks")
class IconAssetTests(unittest.TestCase):
    def test_menu_bar_icon_is_black_artwork_on_a_clear_plate(self):
        with Image.open(ASSETS / "siliconnet_tray.png") as source:
            icon = source.convert("RGBA")

        self.assertEqual(icon.width, icon.height)
        # The white plate must be gone, or a template image shows a solid block.
        self.assertEqual(icon.getpixel((0, 0))[3], 0)
        # Every channel is black; macOS derives the shape from alpha alone.
        for channel in ("R", "G", "B"):
            self.assertEqual(icon.getchannel(channel).getextrema(), (0, 0))
        self.assertEqual(icon.getchannel("A").getextrema()[1], 255)

    def test_menu_bar_icon_keeps_padding_around_the_artwork(self):
        with Image.open(ASSETS / "siliconnet_tray.png") as source:
            icon = source.convert("RGBA")

        left, top, right, bottom = icon.getbbox()
        self.assertGreaterEqual(min(left, top), 4)
        self.assertGreaterEqual(min(icon.width - right, icon.height - bottom), 4)

    def test_app_icon_keeps_its_opaque_plate(self):
        with Image.open(ASSETS / "siliconnet_app.png") as source:
            icon = source.convert("RGBA")

        self.assertEqual(icon.width, icon.height)
        self.assertEqual(icon.getpixel((icon.width // 2, icon.height // 2))[3], 255)


class _FakeButton:
    def __init__(self):
        self.images = []

    def setImage_(self, image):
        self.images.append(image)


class _FakeStatusItem:
    def __init__(self):
        self._button = _FakeButton()

    def button(self):
        return self._button


class _FakeNSImage:
    def __init__(self):
        self.template = None

    def setTemplate_(self, value):
        self.template = value


class _FakeIcon:
    image_factory = _FakeNSImage

    def __init__(self, *args):
        self.args = args
        self._status_item = _FakeStatusItem()
        self._icon_image = None

    def _assert_image(self):
        self._icon_image = self.image_factory() if self.image_factory else None


def _fake_pystray(icon_class):
    return types.SimpleNamespace(Icon=icon_class)


class StatusBarIconTests(unittest.TestCase):
    def _icon(self, icon_class):
        with patch("siliconnet.tray.pystray", _fake_pystray(icon_class)):
            icon = status_bar_icon_class()("siliconnet", None, "SiliconNet", None)
            icon._assert_image()
        return icon

    def test_image_is_marked_as_a_template_and_reapplied_to_the_button(self):
        icon = self._icon(_FakeIcon)

        self.assertTrue(icon._icon_image.template)
        self.assertEqual(icon._status_item.button().images, [icon._icon_image])

    def test_missing_image_is_tolerated(self):
        class _NoImage(_FakeIcon):
            image_factory = None

        icon = self._icon(_NoImage)

        self.assertIsNone(icon._icon_image)
        self.assertEqual(icon._status_item.button().images, [])

    def test_unsupported_selector_does_not_break_the_icon(self):
        class _Unsupported(_FakeNSImage):
            def setTemplate_(self, value):
                raise AttributeError("setTemplate_ is unavailable")

        class _UnsupportedIcon(_FakeIcon):
            image_factory = _Unsupported

        icon = self._icon(_UnsupportedIcon)

        self.assertIsNone(icon._icon_image.template)
        self.assertEqual(icon._status_item.button().images, [])


if __name__ == "__main__":
    unittest.main()
