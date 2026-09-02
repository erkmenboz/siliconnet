"""Live local network connection snapshots for the macOS dashboard.

Uses the built-in ``lsof`` (no third-party tools, no root needed for the
user's own processes) and keeps the same NetworkFlow contract as the other
platform ports so the dashboard code stays shared.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import fnmatch
import ipaddress
import platform
import shutil
import subprocess
import time
from typing import Any, Callable


@dataclass(frozen=True)
class NetworkFlow:
    process_name: str
    pid: int
    protocol: str
    local_address: str
    local_port: int | None
    remote_address: str
    remote_port: int | None
    state: str
    exception_entry: str
    is_exception: bool


_SERVICE_PORTS = {
    "http": 80,
    "https": 443,
    "domain": 53,
    "ssh": 22,
}


def _run_command(args: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _parse_port(value: str) -> int | None:
    value = (value or "").strip().strip("[]")
    if value in {"", "*"}:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return _SERVICE_PORTS.get(value.lower())


def _parse_endpoint(value: str) -> tuple[str, int | None]:
    value = value.strip()
    if not value or value in {"*:*", "*"}:
        return "*", None
    if value.startswith("["):
        end = value.find("]")
        if end >= 0:
            host = value[1:end]
            port_text = value[end + 2:] if value[end + 1:end + 2] == ":" else ""
            return _strip_zone(host), _parse_port(port_text)
    if ":" not in value:
        return _strip_zone(value), None
    host, port_text = value.rsplit(":", 1)
    if host == "":
        host = "*"
    return _strip_zone(host.strip("[]")), _parse_port(port_text)


def _strip_zone(address: str) -> str:
    # lsof may append an interface zone id to IPv6 addresses: fe80::1%en0
    return address.split("%", 1)[0]


def _is_local_address(address: str) -> bool:
    if address in {"*", "0.0.0.0", "::", "::1", "127.0.0.1", "localhost"}:
        return True
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local


def _matches_bypass(address: str, entries: list[str]) -> bool:
    if not address or address == "*":
        return False
    normalized = address.lower()
    for raw_entry in entries:
        entry = str(raw_entry or "").strip().lower()
        if not entry:
            continue
        if entry == "<local>" and _is_local_address(normalized):
            return True
        if entry == normalized or fnmatch.fnmatch(normalized, entry):
            return True
    return False


def exception_entry_for_flow(flow: NetworkFlow | dict[str, Any]) -> str:
    remote_address = flow["remote_address"] if isinstance(flow, dict) else flow.remote_address
    remote_port = flow["remote_port"] if isinstance(flow, dict) else flow.remote_port
    if not remote_address or remote_address == "*" or remote_port is None:
        return ""
    if _is_local_address(remote_address):
        return ""
    return remote_address


def _parse_lsof(text: str, bypass_entries: list[str]) -> list[NetworkFlow]:
    """Parse ``lsof -nP +c 0 -iTCP -iUDP`` output.

    Example row (columns are space-separated; COMMAND can contain spaces, so
    the PID is located as the first all-digit token):

    Discord  1234 user  55u  IPv4 0x1a2b3c  0t0  TCP 192.168.1.5:51234->162.159.128.233:443 (ESTABLISHED)
    """
    flows: list[NetworkFlow] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("COMMAND "):
            continue
        if "->" not in line:
            continue
        parts = line.split()
        pid_index = next((i for i, token in enumerate(parts) if token.isdigit()), None)
        if pid_index is None:
            continue
        process_name = " ".join(parts[:pid_index]).strip()
        try:
            pid = int(parts[pid_index])
        except (TypeError, ValueError):
            continue
        arrow_index = next((i for i, token in enumerate(parts) if "->" in token), None)
        if arrow_index is None:
            continue
        protocol = ""
        for token in reversed(parts[pid_index + 1:arrow_index]):
            upper = token.upper()
            if upper in {"TCP", "UDP"}:
                protocol = upper
                break
        if protocol not in {"TCP", "UDP"}:
            continue
        state = ""
        for token in parts[arrow_index + 1:]:
            cleaned = token.strip("()")
            if cleaned:
                state = cleaned.upper()
                break
        local_raw, remote_raw = parts[arrow_index].split("->", 1)
        local_address, local_port = _parse_endpoint(local_raw)
        remote_address, remote_port = _parse_endpoint(remote_raw)
        probe = NetworkFlow(
            process_name=process_name,
            pid=pid,
            protocol=protocol,
            local_address=local_address,
            local_port=local_port,
            remote_address=remote_address,
            remote_port=remote_port,
            state=state,
            exception_entry="",
            is_exception=_matches_bypass(remote_address, bypass_entries),
        )
        flows.append(
            NetworkFlow(
                process_name=probe.process_name,
                pid=probe.pid,
                protocol=probe.protocol,
                local_address=probe.local_address,
                local_port=probe.local_port,
                remote_address=probe.remote_address,
                remote_port=probe.remote_port,
                state=probe.state,
                exception_entry=exception_entry_for_flow(probe),
                is_exception=probe.is_exception,
            )
        )
    return flows


class NetworkMonitor:
    def __init__(
        self,
        *,
        system: str | None = None,
        runner: Callable[[list[str], float], subprocess.CompletedProcess[str]] = _run_command,
        which: Callable[[str], str | None] = shutil.which,
        cache_ttl: float = 3.0,
    ):
        self.system = system or platform.system()
        self.runner = runner
        self.which = which
        self.cache_ttl = cache_ttl
        self._cached_flows: list[NetworkFlow] = []
        self._cached_at = 0.0
        self._last_error = ""

    def supported(self) -> bool:
        return self.system.lower() == "darwin" and bool(self.which("lsof"))

    def snapshot(
        self,
        proxy_bypass: list[str] | None = None,
        always_bypass: list[str] | None = None,
        *,
        limit: int = 250,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        if self.system.lower() != "darwin":
            return self._unsupported("network flow snapshot is only supported on macOS")
        if not self.which("lsof"):
            return self._unsupported("lsof command was not found; network flows are unavailable")

        now = time.time()
        bypass_entries = list(always_bypass or []) + list(proxy_bypass or [])
        if use_cache and self._cached_flows and now - self._cached_at < self.cache_ttl:
            flows = self._apply_exception_flags(self._cached_flows, bypass_entries)
        else:
            try:
                result = self._load_lsof()
                flows = _parse_lsof(result.stdout, bypass_entries)
                self._cached_flows = flows
                self._cached_at = now
                self._last_error = ""
            except Exception as exc:
                flows = []
                self._last_error = str(exc)

        flows.sort(key=lambda item: (item.process_name.lower(), item.pid, item.protocol, item.remote_address))
        limited = flows[: max(0, limit)]
        return {
            "supported": True,
            "flows": [asdict(item) for item in limited],
            "summary": self._summary(flows, supported=True),
            "error": self._last_error,
        }

    def _unsupported(self, error: str) -> dict[str, Any]:
        self._last_error = error
        return {
            "supported": False,
            "flows": [],
            "summary": self._summary([], supported=False),
            "error": error,
        }

    def _load_lsof(self) -> subprocess.CompletedProcess[str]:
        # +c 0 keeps full command names; -nP avoids DNS/port-name lookups so
        # the snapshot is fast and does not leak lookups to the system DNS.
        result = self.runner(["lsof", "-nP", "+c", "0", "-iTCP", "-iUDP"], 5.0)
        # lsof exits with 1 when nothing matched; treat that as an empty list.
        if result.returncode not in (0, 1):
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(detail or "lsof failed")
        return result

    def last_summary(self) -> dict[str, Any]:
        return self._summary(self._cached_flows, supported=self.supported())

    def _apply_exception_flags(self, flows: list[NetworkFlow], bypass_entries: list[str]) -> list[NetworkFlow]:
        updated: list[NetworkFlow] = []
        for flow in flows:
            updated.append(
                NetworkFlow(
                    process_name=flow.process_name,
                    pid=flow.pid,
                    protocol=flow.protocol,
                    local_address=flow.local_address,
                    local_port=flow.local_port,
                    remote_address=flow.remote_address,
                    remote_port=flow.remote_port,
                    state=flow.state,
                    exception_entry=flow.exception_entry,
                    is_exception=_matches_bypass(flow.remote_address, bypass_entries),
                )
            )
        return updated

    def _summary(self, flows: list[NetworkFlow], *, supported: bool) -> dict[str, Any]:
        process_counts: dict[str, int] = {}
        addable = 0
        for flow in flows:
            name = flow.process_name or (f"PID {flow.pid}" if flow.pid else "unknown")
            process_counts[name] = process_counts.get(name, 0) + 1
            if flow.exception_entry and not flow.is_exception:
                addable += 1
        top_processes = [
            {"process_name": name, "count": count}
            for name, count in sorted(process_counts.items(), key=lambda item: item[1], reverse=True)[:8]
        ]
        return {
            "supported": supported,
            "flow_count": len(flows),
            "addable_count": addable,
            "exception_count": sum(1 for flow in flows if flow.is_exception),
            "top_processes": top_processes,
            "last_updated": int(self._cached_at) if self._cached_at else 0,
        }
