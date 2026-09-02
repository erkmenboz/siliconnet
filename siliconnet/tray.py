"""System tray (macOS status bar) and user-triggered lifecycle actions.

Uses pystray, which renders a native ``NSStatusItem`` on macOS through
PyObjC. Confirmation dialogs use ``osascript`` so no extra GUI toolkit is
needed, and the tray loop runs on the main thread as macOS requires.
"""

from __future__ import annotations

from dataclasses import dataclass
import asyncio
import math
import os
import subprocess
import sys
import threading
import webbrowser
from typing import Any, Awaitable, Callable

from .os_integration import get_user_language
from .status_bar import status_bar_icon_class

try:
    import pystray
    from PIL import Image, ImageDraw
    PYSTRAY_AVAILABLE = True
except ImportError:
    pystray = None
    Image = None
    ImageDraw = None
    PYSTRAY_AVAILABLE = False

TRAY_AVAILABLE = PYSTRAY_AVAILABLE

# Source resolution for the status bar glyph. status_bar.py resamples it to
# whatever the menu bar actually asks for, so keep headroom above 22pt @2x.
TRAY_ICON_SIZE = 128
DNS_FLUSH_COMMAND = ["dscacheutil", "-flushcache"]
MDNS_RELOAD_COMMAND = ["killall", "-HUP", "mDNSResponder"]

STATUS_COLORS = {
    "running": (67, 181, 129),
    "stopped": (150, 150, 150),
    "error": (240, 71, 71),
    "reconnecting": (250, 166, 26),
}
STATUS_TEXT = {
    "running": "Active",
    "stopped": "Stopped",
    "error": "Connection Error",
    "reconnecting": "Reconnecting",
}


@dataclass
class TrayRuntimeContext:
    version: str
    logger: Any
    local_host: str
    web_port: int
    log_file: str
    app_file: str
    python_executable: str
    get_status: Callable[[], str]
    get_ping_ms: Callable[[], int]
    get_loop: Callable[[], Any]
    get_shutdown_event: Callable[[], Any]
    set_running: Callable[[bool], None]
    force_save: Callable[[], None]
    set_proxy_enabled: Callable[[bool], None]
    release_instance_lock: Callable[[], None]
    resolve_bypass_ips: Callable[[], Awaitable[Any]]
    asset_dir: str | None = None


def build_status_title(status: str, ping_ms: int) -> str:
    ping_str = f" | {ping_ms}ms" if ping_ms > 0 else ""
    return f"SiliconNet - {STATUS_TEXT.get(status, status)}{ping_str}"


def build_full_shutdown_prompt(lang: str) -> tuple[str, str]:
    if lang == "tr":
        return (
            "SiliconNet - Tam Kapatma",
            "Bu islem asagidakileri yapacaktir:\n\n"
            "1. DPI Bypass proxy'si durdurulacak\n"
            "2. macOS proxy ayarlari onceki haline dondurulecek\n"
            "3. DNS onbellegi temizlenecek (dscacheutil -flushcache)\n\n"
            "Diger uygulamalariniz etkilenmeyecektir.\n\n"
            "Devam etmek istiyor musunuz?",
        )
    if lang == "de":
        return (
            "SiliconNet - Vollstaendiges Herunterfahren",
            "Folgende Aktionen werden ausgefuehrt:\n\n"
            "1. DPI-Bypass-Proxy wird gestoppt\n"
            "2. macOS-Proxy-Einstellungen werden zurueckgesetzt\n"
            "3. DNS-Cache wird geleert (dscacheutil -flushcache)\n\n"
            "Andere Anwendungen werden nicht beeintraechtigt.\n\n"
            "Moechten Sie fortfahren?",
        )
    return (
        "SiliconNet - Full Shutdown",
        "The following actions will be performed:\n\n"
        "1. DPI Bypass proxy will be stopped\n"
        "2. macOS proxy settings will be restored\n"
        "3. DNS cache will be flushed (dscacheutil -flushcache)\n\n"
        "Other applications will not be affected.\n\n"
        "Do you want to continue?",
    )


def build_confirm_buttons(lang: str) -> tuple[str, str]:
    if lang == "tr":
        return ("Vazgec", "Devam Et")
    if lang == "de":
        return ("Abbrechen", "Fortfahren")
    return ("Cancel", "Continue")


def escape_applescript(value: str) -> str:
    """Quote a Python string for use inside an AppleScript string literal."""
    escaped = value.replace("\\", "\\\\")
    escaped = escaped.replace('"', '\\"')
    return escaped.replace("\n", "\\n")


def build_confirm_script(title: str, message: str, buttons: tuple[str, str]) -> str:
    cancel_button, confirm_button = buttons
    return (
        f'display dialog "{escape_applescript(message)}" '
        f'with title "{escape_applescript(title)}" '
        f'buttons {{"{escape_applescript(cancel_button)}", "{escape_applescript(confirm_button)}"}} '
        f'default button "{escape_applescript(confirm_button)}" '
        "with icon caution"
    )


def confirm_dialog(title: str, message: str, lang: str, logger=None) -> bool:
    """Show a native confirmation dialog; assume consent if osascript is gone."""
    script = build_confirm_script(title, message, build_confirm_buttons(lang))
    try:
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=300)
    except FileNotFoundError:
        if logger:
            logger.warning("osascript was not found; full shutdown confirmation was skipped")
        return True
    except subprocess.SubprocessError:
        return False
    return res.returncode == 0


def _candidate_icon_paths(app_dir: str | None, names: list[str]) -> list[str]:
    roots: list[str] = []
    frozen_dir = getattr(sys, "_MEIPASS", None)
    if frozen_dir:
        roots.append(frozen_dir)
    if app_dir:
        roots.append(app_dir)

    paths: list[str] = []
    seen: set[str] = set()
    for root in roots:
        for rel_dir in ("assets", ""):
            for name in names:
                path = os.path.join(root, rel_dir, name)
                norm = os.path.abspath(path)
                if norm not in seen:
                    seen.add(norm)
                    paths.append(norm)
    return paths


def load_tray_icon(app_dir: str | None = None, size: int = TRAY_ICON_SIZE):
    if not PYSTRAY_AVAILABLE:
        return None

    for path in _candidate_icon_paths(
        app_dir,
        ["siliconnet_tray.png", "tray_icon.png", "icon_tray.png", "siliconnet_app.png", "app_icon.png"],
    ):
        if not os.path.exists(path):
            continue
        try:
            image = Image.open(path).convert("RGBA")
            image.thumbnail((size, size), Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            x = (size - image.width) // 2
            y = (size - image.height) // 2
            canvas.alpha_composite(image, (x, y))
            return canvas
        except Exception:
            continue
    return None


def create_icon(color, app_dir: str | None = None):
    if not PYSTRAY_AVAILABLE:
        return None

    asset_icon = load_tray_icon(app_dir)
    if asset_icon is not None:
        return asset_icon

    size = TRAY_ICON_SIZE
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx, cy = size // 2, size // 2
    radius = int(size * 0.40)
    pts = [
        (
            cx + radius * math.cos(math.radians(angle - 90)),
            cy + radius * math.sin(math.radians(angle - 90)),
        )
        for angle in range(0, 360, 60)
    ]
    stroke = max(2, size // 15)
    draw.polygon(pts, outline=color)
    draw.line([(cx, cy), (cx, cy - int(radius * 0.55))], fill=color, width=stroke)
    draw.line([(cx, cy), (cx + int(radius * 0.40), cy + int(radius * 0.25))], fill=color, width=stroke)
    draw.ellipse([cx - stroke, cy - stroke, cx + stroke, cy + stroke], fill=color)
    return img


class TrayManager:
    def __init__(self, context: TrayRuntimeContext):
        self.ctx = context

    def signal_shutdown(self) -> None:
        loop = self.ctx.get_loop()
        event = self.ctx.get_shutdown_event()
        if loop and event:
            loop.call_soon_threadsafe(event.set)

    def update(self, icon) -> None:
        if not icon:
            return
        try:
            status = self.ctx.get_status()
            icon.icon = create_icon(STATUS_COLORS.get(status, STATUS_COLORS["stopped"]), self.ctx.asset_dir)
            icon.title = build_status_title(status, self.ctx.get_ping_ms())
            icon.update_menu()
        except Exception:
            pass

    def open_dashboard(self, _icon=None, _item=None) -> None:
        webbrowser.open(f"http://{self.ctx.local_host}:{self.ctx.web_port}")

    def refresh_ips(self, _icon=None, _item=None) -> None:
        loop = self.ctx.get_loop()
        if loop:
            asyncio.run_coroutine_threadsafe(self.ctx.resolve_bypass_ips(), loop)

    def open_log(self, _icon=None, _item=None) -> None:
        if os.path.exists(self.ctx.log_file):
            subprocess.Popen(["open", "-t", self.ctx.log_file])

    def exit(self, icon=None, _item=None) -> None:
        self.ctx.logger.info("User exit")
        self.ctx.set_running(False)
        self.ctx.force_save()
        self.ctx.set_proxy_enabled(False)
        self.signal_shutdown()
        if icon:
            icon.stop()

    def _flush_dns_cache(self) -> None:
        try:
            subprocess.run(DNS_FLUSH_COMMAND, capture_output=True, timeout=15)
        except (FileNotFoundError, subprocess.SubprocessError) as exc:
            self.ctx.logger.warning(f"DNS cache flush skipped: {exc}")
            return
        # mDNSResponder only reloads for root; a plain call is a harmless no-op.
        try:
            subprocess.run(MDNS_RELOAD_COMMAND, capture_output=True, timeout=15)
        except (FileNotFoundError, subprocess.SubprocessError):
            pass
        self.ctx.logger.info("[OK] DNS cache flushed via dscacheutil.")

    def _run_full_shutdown(self, icon) -> None:
        lang = get_user_language()
        title, message = build_full_shutdown_prompt(lang)
        if not confirm_dialog(title, message, lang, self.ctx.logger):
            return

        self.ctx.logger.info("Full shutdown initiated on macOS")
        self.ctx.set_running(False)
        self.ctx.force_save()
        self.ctx.set_proxy_enabled(False)
        self.signal_shutdown()
        self._flush_dns_cache()

        if icon:
            icon.stop()

    def full_shutdown(self, icon=None, _item=None) -> None:
        threading.Thread(target=self._run_full_shutdown, args=(icon,), daemon=True).start()

    def restart(self, icon=None, _item=None) -> None:
        self.ctx.set_running(False)
        self.signal_shutdown()
        if icon:
            icon.stop()
        self.ctx.release_instance_lock()
        source_dir = os.path.dirname(os.path.abspath(self.ctx.app_file))
        if os.path.basename(source_dir) == "siliconnet":
            source_dir = os.path.dirname(source_dir)
        subprocess.Popen([
            self.ctx.python_executable,
            "-c",
            (
                "import subprocess,time;"
                "time.sleep(2);"
                f"subprocess.Popen([{self.ctx.python_executable!r}, '-m', 'siliconnet'], cwd={source_dir!r})"
            ),
        ])

    def _status_label(self, _item=None) -> str:
        status = self.ctx.get_status()
        return f"Status: {STATUS_TEXT.get(status, status)}"

    def _ping_label(self, _item=None) -> str:
        ping = self.ctx.get_ping_ms()
        return f"Ping: {ping}ms" if ping > 0 else "Ping: --"

    def build_menu(self):
        return pystray.Menu(
            pystray.MenuItem(f"SiliconNet v{self.ctx.version}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(self._status_label, None, enabled=False),
            pystray.MenuItem(self._ping_label, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Dashboard", self.open_dashboard, default=True),
            pystray.MenuItem("Refresh IPs", self.refresh_ips),
            pystray.MenuItem("Log File", self.open_log),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Restart", self.restart),
            pystray.MenuItem("Exit", self.exit),
            pystray.MenuItem("Full Shutdown (Reset Network)", self.full_shutdown),
        )

    def setup(self):
        if not TRAY_AVAILABLE:
            raise RuntimeError("Tray dependencies are not available")

        self.ctx.logger.info("Using pystray status bar item (native macOS)")
        return status_bar_icon_class(pystray)(
            "siliconnet",
            create_icon(STATUS_COLORS["running"], self.ctx.asset_dir),
            "SiliconNet - Active",
            self.build_menu(),
        )
