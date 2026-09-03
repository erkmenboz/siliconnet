"""Proxy compatibility for apps that ignore the macOS system proxy.

The system proxy set via ``networksetup`` is honored by every CFNetwork /
NSURLSession app (Safari, WhatsApp, iCloud, ...) and by Chromium-based
browsers, but a class of embedded HTTP stacks never reads it. The canonical
case is Discord's Rust updater (reqwest/hyper): it connects directly, lands on
the ISP's DNS-poisoned block page, gets a forged certificate
(``CN=*.btk.gov.tr``), refuses it with ``-67843 The certificate was not
trusted``, and leaves the whole app stuck on "checking for updates". These
stacks do honor the de-facto standard proxy environment variables
(``HTTP_PROXY`` / ``HTTPS_PROXY`` / ``ALL_PROXY``).

While SiliconNet owns the system proxy, this module publishes the proxy
address into the user's launchd session environment with ``launchctl setenv``.
GUI apps launched afterwards (Dock, Finder, Spotlight — all launchd children)
inherit it. Chromium ignores these variables (it uses its own proxy config
service) and CFNetwork apps ignore them as well, so the only apps affected are
exactly the ones that are broken without this. ``NO_PROXY`` keeps loopback
traffic local.

The variables live only in the current login session: they are re-published
idempotently while SiliconNet runs and removed when SiliconNet restores the
previous proxy state, so a Mac without SiliconNet running is left untouched.
"""

from __future__ import annotations

import subprocess

ENV_PROXY_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)
ENV_BYPASS_VARS = ("NO_PROXY", "no_proxy")
ENV_BYPASS_VALUE = "localhost,127.0.0.1,::1"

_PROXY_PREFIXES = ("http://127.0.0.1:", "http://localhost:", "http://[::1]:")


def proxy_env_value(host: str, port: int) -> str:
    return f"http://{host}:{port}"


def _looks_like_ours(value: str) -> bool:
    return (value or "").strip().lower().startswith(_PROXY_PREFIXES)


def _launchctl(args: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, timeout=timeout)


def _getenv(name: str) -> str:
    try:
        res = _launchctl(["getenv", name], timeout=3)
    except Exception:
        return ""
    if res.returncode != 0:
        return ""
    return (res.stdout or "").strip()


def _setenv(name: str, value: str) -> bool:
    try:
        res = _launchctl(["setenv", name, value])
    except Exception:
        return False
    return res.returncode == 0


def _unsetenv(name: str) -> bool:
    try:
        res = _launchctl(["unsetenv", name])
    except Exception:
        return False
    return res.returncode == 0


def is_proxy_env_published(host: str, port: int) -> bool:
    """True when the launchd session already advertises our proxy."""
    return _getenv("HTTPS_PROXY") == proxy_env_value(host, port)


def ensure_proxy_env(host: str, port: int, logger=None) -> bool:
    """Idempotently publish the proxy env vars into the launchd session.

    Only shells out to ``launchctl setenv`` when a value is missing or stale,
    so the periodic proxy-ownership check can call this freely.
    """
    want = proxy_env_value(host, port)
    if is_proxy_env_published(host, port) and _getenv("NO_PROXY") == ENV_BYPASS_VALUE:
        # launchctl values outlive the process, so a restart usually lands here
        # and would otherwise say nothing at all -- leaving no trace that the
        # env compat layer is active. Say so at debug level.
        if logger:
            logger.debug(f"[APP-COMPAT] launchd proxy env already published ({want})")
        return True
    ok = True
    for name in ENV_PROXY_VARS:
        if _getenv(name) != want:
            ok = _setenv(name, want) and ok
    for name in ENV_BYPASS_VARS:
        if _getenv(name) != ENV_BYPASS_VALUE:
            ok = _setenv(name, ENV_BYPASS_VALUE) and ok
    if logger:
        if ok:
            logger.info(f"[APP-COMPAT] launchd proxy env published ({want}); relaunch affected apps (e.g. Discord)")
        else:
            logger.warning("[APP-COMPAT] launchctl setenv failed; apps ignoring the system proxy stay unreachable")
    return ok


def remove_proxy_env(logger=None) -> bool:
    """Remove the variables, but only values that look SiliconNet-owned.

    A pre-existing foreign proxy setting in the launchd environment is left
    untouched rather than clobbered.
    """
    ok = True
    for name in ENV_PROXY_VARS:
        if _looks_like_ours(_getenv(name)):
            ok = _unsetenv(name) and ok
    for name in ENV_BYPASS_VARS:
        if _getenv(name) == ENV_BYPASS_VALUE:
            ok = _unsetenv(name) and ok
    if logger and ok:
        logger.info("[APP-COMPAT] launchd proxy env removed")
    return ok
