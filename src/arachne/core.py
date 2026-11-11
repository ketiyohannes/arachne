"""Shared plumbing: local state directory, config, and the Tailscale device list."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

TAILSCALE_PATHS = (
    "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
    r"C:\Program Files\Tailscale\tailscale.exe",
)

# Subprocesses we spawn on Windows must not flash a console window.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class Error(Exception):
    """A problem to report to the user (no traceback)."""


# ---------------------------------------------------------------------------- local state


def state_dir() -> Path:
    """Per-user arachne directory (jobs, activity log, bridge credentials, config)."""
    path = Path(os.environ.get("ARACHNE_HOME") or Path.home() / ".arachne")
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_config() -> dict:
    try:
        return json.loads((state_dir() / "config.json").read_text())
    except (OSError, ValueError):
        return {}


def save_config(config: dict) -> None:
    write_private(state_dir() / "config.json", json.dumps(config, indent=2))


def write_private(path: Path, text: str) -> None:
    """Write a file only the current user can read (best effort on Windows)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)


# ---------------------------------------------------------------------------- tailscale


def tailscale_bin() -> str:
    found = shutil.which("tailscale")
    if found:
        return found
    for path in TAILSCALE_PATHS:
        if os.path.exists(path):
            return path
    raise Error("tailscale is not installed (https://tailscale.com/download)")


def tailscale_status(require_running: bool = True) -> dict:
    """`tailscale status --json`. ARACHNE_TAILSCALE_STATUS points at a JSON file to use instead (tests)."""
    fixture = os.environ.get("ARACHNE_TAILSCALE_STATUS")
    if fixture:
        status = json.loads(Path(fixture).read_text())
    else:
        proc = subprocess.run(
            [tailscale_bin(), "status", "--json"], capture_output=True, text=True, creationflags=NO_WINDOW
        )
        try:
            status = json.loads(proc.stdout)
        except ValueError:
            raise Error(f"could not read tailscale status: {(proc.stderr or proc.stdout).strip()}") from None
    state = status.get("BackendState")
    if require_running and state != "Running":
        raise Error(f"tailscale is not connected (state: {state}); run `tailscale up` or open the Tailscale app")
    return status


def devices(status: dict) -> list[dict]:
    """Every device on the tailnet, this machine included, as simple dicts."""
    running = status.get("BackendState") == "Running"
    out = []
    peers = [(status["Self"], True)] + [(p, False) for p in (status.get("Peer") or {}).values()]
    for node, is_self in peers:
        dns = (node.get("DNSName") or "").rstrip(".")
        ips = node.get("TailscaleIPs") or []
        online = True if is_self else running and bool(node.get("Online"))
        if is_self:
            link = "self"
        elif not online:
            link = "offline"
        else:
            # A direct WireGuard path has a current address; otherwise traffic goes via a relay.
            link = "direct" if node.get("CurAddr") else "relay"
        out.append({
            "name": dns.split(".")[0] if dns else node.get("HostName", ""),
            "hostname": node.get("HostName", ""),
            "dns": dns,
            "ip": ips[0] if ips else "",
            "ips": ips,
            "os": (node.get("OS") or "").lower(),
            "online": online,
            "self": is_self,
            "link": link,
            "relay": node.get("Relay", ""),
            "owner": node.get("UserID"),
        })
    return sorted(out, key=lambda d: (not d["self"], not d["online"], d["name"].lower()))


def find_device(devs: list[dict], query: str) -> dict:
    """Match by MagicDNS name, full DNS name, hostname or Tailscale IP, then by unique prefix."""
    q = query.lower().rstrip(".")
    if q in ("self", "local", "localhost"):
        return next(d for d in devs if d["self"])
    exact = [d for d in devs if q in (d["name"].lower(), d["dns"].lower(), d["hostname"].lower(), *d["ips"])]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise Error(f"'{query}' matches several devices: {', '.join(d['dns'] for d in exact)}; use the full name")
    prefix = [d for d in devs if d["name"].lower().startswith(q) or d["hostname"].lower().startswith(q)]
    if len(prefix) == 1:
        return prefix[0]
    if prefix:
        raise Error(f"'{query}' is ambiguous: {', '.join(d['name'] for d in prefix)}")
    names = ", ".join(d["name"] for d in devs) or "none"
    raise Error(f"no device named '{query}' on your tailnet (devices: {names})")


def resolve(query: str, must_be_online: bool = True) -> dict:
    status = tailscale_status(require_running=False)
    dev = find_device(devices(status), query)
    if not dev["self"]:
        tailscale_status()  # this machine needs no network; anything else needs Tailscale connected
    if must_be_online and not dev["online"]:
        raise Error(f"{dev['name']} is offline in Tailscale")
    return dev
