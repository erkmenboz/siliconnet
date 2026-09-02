"""macOS proxy, autostart, language, and proxy restore integration.

System proxy is managed with the built-in ``networksetup`` tool, applied to
every enabled network service (Wi-Fi, Ethernet, ...). On most personal Macs
the logged-in user is an admin account and ``networksetup`` works without a
password prompt; when macOS denies the change (standard account or the
"require administrator password" security option), the same batch is replayed
once through ``osascript ... with administrator privileges``, which shows the
native macOS password dialog.

Autostart uses a LaunchAgent in ``~/Library/LaunchAgents`` (user-level, no
root). The previous proxy state of every service is backed up to
``macos_proxy_state.json`` and restored when SiliconNet exits or is disabled.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from typing import Any

from .settings import default_data_dir


PROXY_BACKUP_FILE = "macos_proxy_state.json"
LAUNCH_AGENT_DOMAIN = "com.siliconnet"


@dataclass(frozen=True)
class ProxyBackend:
    name: str
    supported: bool
    error: str = ""


class _AdminRequired(RuntimeError):
    """Raised when networksetup refuses a change for missing admin rights."""


def _run(args: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def _backup_path(app_dir: str) -> str:
    return os.path.join(app_dir, PROXY_BACKUP_FILE)


def detect_proxy_backend() -> ProxyBackend:
    if shutil.which("networksetup"):
        return ProxyBackend("macos-networksetup", True)
    return ProxyBackend(
        "macos-networksetup",
        False,
        error="networksetup was not found; proxy integration is unavailable on this system.",
    )


def build_bypass_list(always_bypass: list[str], user_bypass: list[str] | None = None) -> str:
    entries: list[str] = []
    seen: set[str] = set()
    for item in list(always_bypass or []) + list(user_bypass or []):
        if not item:
            continue
        # macOS bypass domains use "*.local" for link-local names.
        normalized = "*.local" if item == "<local>" else item
        if normalized not in seen:
            seen.add(normalized)
            entries.append(normalized)
    return ",".join(entries)


def is_app_proxy_server(server: str | None, host: str, port: int) -> bool:
    return (server or "").strip().lower() == f"{host}:{port}".lower()


def _is_admin_error(res: subprocess.CompletedProcess[str]) -> bool:
    detail = f"{res.stderr}\n{res.stdout}".lower()
    return (
        "admin" in detail
        or "root" in detail
        or "permission" in detail
        or "not authorized" in detail
        or "authorization" in detail
    )


def _require_success(res: subprocess.CompletedProcess[str], action: str) -> None:
    if res.returncode != 0:
        if _is_admin_error(res):
            raise _AdminRequired(action)
        detail = (res.stderr or res.stdout or "").strip()
        raise RuntimeError(f"{action} failed: {detail or res.returncode}")


def _networksetup(args: list[str], timeout: float = 5.0) -> str:
    res = _run(["networksetup", *args], timeout=timeout)
    _require_success(res, f"networksetup {args[0] if args else ''}")
    return res.stdout


def list_network_services() -> list[str]:
    """Return enabled network services (Wi-Fi, Ethernet, ...), disabled skipped."""
    res = _run(["networksetup", "-listallnetworkservices"])
    _require_success(res, "networksetup -listallnetworkservices")
    services: list[str] = []
    for line in res.stdout.splitlines():
        name = line.strip()
        if not name:
            continue
        if "asterisk" in name.lower():
            continue
        if name.startswith("*"):
            continue
        services.append(name)
    return services


def _parse_proxy_info(text: str) -> dict[str, Any]:
    info: dict[str, Any] = {"enabled": False, "server": "", "port": 0}
    for line in (text or "").splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key == "enabled":
            info["enabled"] = value.lower() in {"yes", "1", "true", "on"}
        elif key == "server":
            info["server"] = value
        elif key == "port":
            try:
                info["port"] = int(value)
            except (TypeError, ValueError):
                info["port"] = 0
    return info


def _get_webproxy_state(service: str, secure: bool = False) -> dict[str, Any]:
    flag = "-getsecurewebproxy" if secure else "-getwebproxy"
    return _parse_proxy_info(_networksetup([flag, service]))


def _get_bypass_domains(service: str) -> list[str]:
    res = _run(["networksetup", "-getproxybypassdomains", service])
    if res.returncode != 0:
        return []
    output = res.stdout or ""
    if "aren't any" in output or "no bypass" in output.lower():
        return []
    return [line.strip() for line in output.splitlines() if line.strip()]


def _read_service_state(service: str) -> dict[str, Any]:
    return {
        "web": _get_webproxy_state(service, secure=False),
        "secure": _get_webproxy_state(service, secure=True),
        "bypass": _get_bypass_domains(service),
    }


def _read_backend_state(_backend: str) -> dict[str, Any]:
    services: dict[str, Any] = {}
    for service in list_network_services():
        try:
            services[service] = _read_service_state(service)
        except Exception:
            continue
    return {"services": services}


def _proxy_commands_for_state(service: str, state: dict[str, Any]) -> list[list[str]]:
    commands: list[list[str]] = []
    for kind, set_flag, state_flag in (
        ("web", "-setwebproxy", "-setwebproxystate"),
        ("secure", "-setsecurewebproxy", "-setsecurewebproxystate"),
    ):
        proxy = dict(state.get(kind) or {})
        if proxy.get("enabled"):
            server = str(proxy.get("server") or "").strip()
            port = int(proxy.get("port") or 0)
            if server and port:
                commands.append(["networksetup", set_flag, service, server, str(port)])
                commands.append(["networksetup", state_flag, service, "on"])
                continue
        commands.append(["networksetup", state_flag, service, "off"])
    bypass = [str(entry) for entry in (state.get("bypass") or []) if str(entry).strip()]
    commands.append(["networksetup", "-setproxybypassdomains", service, *(bypass or ["Empty"])])
    return commands


def _enable_commands(service: str, host: str, port: int, bypass_entries: list[str]) -> list[list[str]]:
    return _proxy_commands_for_state(service, {
        "web": {"enabled": True, "server": host, "port": port},
        "secure": {"enabled": True, "server": host, "port": port},
        "bypass": bypass_entries,
    })


def _run_batch(commands: list[list[str]]) -> None:
    for command in commands:
        res = _run(command)
        _require_success(res, " ".join(command[:2]))


def _run_batch_as_admin(commands: list[list[str]]) -> None:
    """Replay the whole batch once via the native macOS admin password prompt."""
    script_lines = ["set -e"]
    for command in commands:
        script_lines.append(" ".join(shlex.quote(str(part)) for part in command))
    script = "\n".join(script_lines)
    escaped = script.replace("\\", "\\\\").replace('"', '\\"')
    res = _run([
        "osascript",
        "-e",
        f'do shell script "{escaped}" with administrator privileges',
    ], timeout=120)
    if res.returncode != 0:
        detail = (res.stderr or res.stdout or "").strip()
        raise RuntimeError(f"administrator authorization failed or was cancelled: {detail or res.returncode}")


def _apply_commands(commands: list[list[str]]) -> None:
    try:
        _run_batch(commands)
    except _AdminRequired:
        _run_batch_as_admin(commands)


def _enable_backend_proxy(backend: str, host: str, port: int, bypass_list: str) -> None:
    del backend  # macOS has a single backend; kept for interface parity
    bypass_entries = [item.strip() for item in bypass_list.split(",") if item.strip()]
    commands: list[list[str]] = []
    for service in list_network_services():
        commands.extend(_enable_commands(service, host, port, bypass_entries))
    if not commands:
        raise RuntimeError("no enabled network services found")
    _apply_commands(commands)


def _restore_backend_state(backend: str, state: dict[str, Any]) -> None:
    del backend
    commands: list[list[str]] = []
    for service, service_state in (state.get("services") or {}).items():
        commands.extend(_proxy_commands_for_state(service, dict(service_state or {})))
    if commands:
        _apply_commands(commands)


def _load_backup(app_dir: str) -> dict[str, Any] | None:
    path = _backup_path(app_dir)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _save_backup(app_dir: str, backend: str, state: dict[str, Any], host: str, port: int) -> None:
    os.makedirs(app_dir, exist_ok=True)
    existing = _load_backup(app_dir)
    if existing:
        return
    with open(_backup_path(app_dir), "w", encoding="utf-8") as f:
        json.dump({
            "backend": backend,
            "state": state,
            "host": host,
            "port": port,
            "created_at": int(time.time()),
        }, f, indent=2)


def _delete_backup(app_dir: str) -> None:
    try:
        os.remove(_backup_path(app_dir))
    except FileNotFoundError:
        pass


def get_proxy_backup_status(app_dir: str) -> dict[str, Any]:
    backup = _load_backup(app_dir)
    if not backup:
        return {"exists": False}
    return {
        "exists": True,
        "backend": backup.get("backend", ""),
        "created_at": backup.get("created_at", 0),
    }


def get_proxy_summary(app_dir: str, host: str, port: int) -> dict[str, Any]:
    backend = detect_proxy_backend()
    payload = {
        "enabled": False,
        "server": "",
        "owned_by_siliconnet": False,
        "backend": backend.name,
        "supported": backend.supported,
        "error": backend.error,
        "services": [],
        "backup": get_proxy_backup_status(app_dir),
    }
    if not backend.supported:
        return payload
    try:
        state = _read_backend_state(backend.name)
        payload["services"] = sorted(state.get("services") or {})
        for _service, service_state in (state.get("services") or {}).items():
            web = dict((service_state or {}).get("web") or {})
            secure = dict((service_state or {}).get("secure") or {})
            if web.get("enabled") or secure.get("enabled"):
                active = web if web.get("enabled") else secure
                payload["enabled"] = True
                server = str(active.get("server") or "")
                active_port = int(active.get("port") or 0)
                payload["server"] = f"{server}:{active_port}" if server and active_port else ""
                break
        payload["owned_by_siliconnet"] = bool(
            payload["enabled"] and is_app_proxy_server(payload["server"], host, port)
        )
    except Exception as exc:
        payload["error"] = str(exc)
    return payload


def ensure_system_proxy_enabled(
    host: str,
    port: int,
    always_bypass: list[str],
    user_bypass: list[str] | None,
    app_dir: str = "",
    logger=None,
) -> bool:
    summary = get_proxy_summary(app_dir, host, port)
    if summary.get("owned_by_siliconnet"):
        return True
    return set_system_proxy(True, host, port, always_bypass, user_bypass, app_dir, logger=logger)


def recover_orphaned_proxy(host: str, port: int, app_dir: str, logger=None) -> bool:
    summary = get_proxy_summary(app_dir, host, port)
    if not summary.get("owned_by_siliconnet") and not summary.get("backup", {}).get("exists"):
        return False
    restored = set_system_proxy(False, host, port, [], [], app_dir, logger=logger)
    if restored and logger:
        logger.info("[PROXY] Cleared stale SiliconNet proxy on macOS")
    return restored


def _disable_commands(host: str, port: int) -> list[list[str]]:
    """Turn SiliconNet's proxy off on services that point at host:port (no backup case)."""
    commands: list[list[str]] = []
    for service in list_network_services():
        try:
            state = _read_service_state(service)
        except Exception:
            continue
        target: dict[str, Any] = {"bypass": state.get("bypass") or []}
        for kind in ("web", "secure"):
            proxy = dict(state.get(kind) or {})
            server = f"{proxy.get('server') or ''}:{proxy.get('port') or 0}"
            if proxy.get("enabled") and is_app_proxy_server(server, host, port):
                target[kind] = {"enabled": False, "server": "", "port": 0}
            else:
                target[kind] = proxy
        if target.get("web") != state.get("web") or target.get("secure") != state.get("secure"):
            commands.extend(_proxy_commands_for_state(service, target))
    return commands


def set_system_proxy(
    enable: bool,
    host: str,
    port: int,
    always_bypass: list[str],
    user_bypass: list[str] | None,
    app_dir: str,
    logger=None,
) -> bool:
    backend = detect_proxy_backend()
    if not backend.supported:
        if logger:
            logger.error(backend.error or "macOS proxy backend unavailable")
        return False
    app_dir = app_dir or default_data_dir()
    try:
        if enable:
            state = _read_backend_state(backend.name)
            _save_backup(app_dir, backend.name, state, host, port)
            _enable_backend_proxy(backend.name, host, port, build_bypass_list(always_bypass, user_bypass))
            if logger:
                logger.info("macOS system proxy enabled via networksetup")
            return True

        backup = _load_backup(app_dir)
        if backup:
            _restore_backend_state(str(backup.get("backend") or backend.name), dict(backup.get("state") or {}))
            _delete_backup(app_dir)
            if logger:
                logger.info("[PROXY] Previous macOS proxy state restored")
            return True

        commands = _disable_commands(host, port)
        if commands:
            _apply_commands(commands)
            if logger:
                logger.info("macOS SiliconNet proxy cleared via networksetup")
        return True
    except Exception as exc:
        if logger:
            logger.error(f"macOS proxy settings error: {exc}")
        return False


def launch_agent_label(name: str) -> str:
    return f"{LAUNCH_AGENT_DOMAIN}.{name}"


def _get_autostart_path(name: str) -> str:
    agents_dir = os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents")
    os.makedirs(agents_dir, exist_ok=True)
    return os.path.join(agents_dir, f"{launch_agent_label(name)}.plist")


def get_autostart(name: str) -> bool:
    return os.path.exists(_get_autostart_path(name))


def _plist_xml(name: str, executable: str, source_dir: str) -> str:
    logs_dir = os.path.join(os.path.expanduser("~"), "Library", "Logs", "SiliconNet")
    os.makedirs(logs_dir, exist_ok=True)
    return "\n".join([
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">',
        '<plist version="1.0">',
        '<dict>',
        f'    <key>Label</key><string>{launch_agent_label(name)}</string>',
        '    <key>ProgramArguments</key>',
        '    <array>',
        f'        <string>{executable}</string>',
        '        <string>-m</string>',
        '        <string>siliconnet</string>',
        '    </array>',
        f'    <key>WorkingDirectory</key><string>{source_dir}</string>',
        '    <key>RunAtLoad</key><true/>',
        '    <key>KeepAlive</key><false/>',
        '    <key>ProcessType</key><string>Interactive</string>',
        f'    <key>StandardOutPath</key><string>{os.path.join(logs_dir, "launchd.out.log")}</string>',
        f'    <key>StandardErrorPath</key><string>{os.path.join(logs_dir, "launchd.err.log")}</string>',
        '</dict>',
        '</plist>',
        '',
    ])


def set_autostart(enable: bool, name: str, script_path: str, executable: str | None = None, logger=None) -> bool:
    path = _get_autostart_path(name)
    try:
        if enable:
            python_exec = executable or sys.executable
            source_dir = os.path.dirname(os.path.abspath(script_path))
            if os.path.basename(source_dir) == "siliconnet":
                source_dir = os.path.dirname(source_dir)
            with open(path, "w", encoding="utf-8") as f:
                f.write(_plist_xml(name, python_exec, source_dir))
            uid = os.getuid() if hasattr(os, "getuid") else None
            domain = f"gui/{uid}" if uid is not None else ""
            loaded = False
            if domain:
                try:
                    _run(["launchctl", "bootout", domain, path], timeout=5)
                except Exception:
                    pass
                try:
                    res = _run(["launchctl", "bootstrap", domain, path], timeout=10)
                    loaded = res.returncode == 0
                except Exception:
                    loaded = False
            if not loaded:
                # Deprecated but functional fallback for older macOS versions.
                _run(["launchctl", "unload", "-w", path], timeout=5)
                res = _run(["launchctl", "load", "-w", path], timeout=10)
                if res.returncode != 0:
                    raise RuntimeError((res.stderr or res.stdout or "launchctl load failed").strip())
            if logger:
                logger.info("macOS autostart enabled (LaunchAgent)")
        else:
            uid = os.getuid() if hasattr(os, "getuid") else None
            if uid is not None and os.path.exists(path):
                try:
                    _run(["launchctl", "bootout", f"gui/{uid}", path], timeout=5)
                except Exception:
                    pass
                try:
                    _run(["launchctl", "unload", "-w", path], timeout=5)
                except Exception:
                    pass
            if os.path.exists(path):
                os.remove(path)
            if logger:
                logger.info("macOS autostart disabled")
        return True
    except Exception as e:
        if logger:
            logger.error(f"macOS autostart error: {e}")
        return False


def get_user_language() -> str:
    lang = ""
    try:
        res = _run(["defaults", "read", "-g", "AppleLocale"], timeout=3)
        if res.returncode == 0:
            lang = res.stdout.strip()
    except Exception:
        pass
    if not lang:
        lang = os.environ.get("LANG", "en_US")
    lang = lang.split("_")[0].split(".")[0].lower()
    if lang in ("tr", "de"):
        return lang
    return "en"
