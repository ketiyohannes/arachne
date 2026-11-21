"""Connecting devices to each other without any manual configuration.

`arachne invite` on a device that is already set up prints one line and waits. That
line, pasted on a new device, installs arachne and calls back here over the tailnet.
The two exchange usernames and SSH keys, and this device passes the newcomer on to the
rest, so every device can reach every other one with nothing left to configure.
"""

from __future__ import annotations

import hmac
import json
import secrets
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from arachne import __version__, agent, desktop, remote
from arachne.core import Error, devices, load_config, tailscale_status

INVITE_MINUTES = 30
REPO_RAW = "https://raw.githubusercontent.com/ketiyohannes/arachne/main"


def own_device_at(ip: str) -> dict | None:
    """The tailnet device behind `ip`, if it belongs to the same Tailscale user as this one.

    Tailscale authenticates every peer address, so this is what stops a device that was
    merely shared into the tailnet from pairing, even if it somehow learned the invite link.
    """
    devs = devices(tailscale_status())
    me = next(d for d in devs if d["self"])
    return next((d for d in devs if ip in d["ips"] and d["owner"] == me["owner"] and not d["self"]), None)


def announce(peers: dict, targets: list[dict]) -> list[str]:
    """Tell each target about `peers`; returns the names that could not be reached."""
    missed = []
    for dev in targets:
        try:
            remote.call_json(dev, "peers-merge", {"peers": peers}, timeout=20)
        except Error:
            missed.append(dev["name"])
    return missed


def invite_server(host: str, token: str, on_join, identify=own_device_at) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def reply(self, status: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:
            if not hmac.compare_digest(self.path.strip("/"), token):
                return self.reply(403, {"error": "this invite is not valid"})
            newcomer = identify(self.client_address[0])
            if not newcomer:
                return self.reply(403, {"error": "sign this device in to the same Tailscale account first"})
            try:
                entry = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                entry = {"user": str(entry["user"]), "key": str(entry["key"])}
                me = next(d for d in devices(tailscale_status()) if d["self"])
                agent.merge_peers({newcomer["name"]: entry})
            except (ValueError, KeyError, TypeError, Error) as e:
                return self.reply(400, {"error": f"could not pair: {e}"})
            known = {**load_config().get("peers", {}), me["name"]: agent.my_entry()}
            self.reply(200, {"name": newcomer["name"], "inviter": me["name"], "peers": known})
            on_join(newcomer, entry)

        def log_message(self, *args) -> None:
            pass

    return ThreadingHTTPServer((host, 0), Handler)


def invite() -> int:
    # This command prints, then waits: flush each line even when the output is piped or logged.
    sys.stdout.reconfigure(line_buffering=True)
    devs = devices(tailscale_status())
    me = next(d for d in devs if d["self"])
    token = secrets.token_urlsafe(18)

    def on_join(newcomer: dict, entry: dict) -> None:
        others = [d for d in devices(tailscale_status()) if d["online"] and not d["self"] and d["name"] != newcomer["name"]]
        missed = announce({newcomer["name"]: entry}, others)
        print(f"  ok  {newcomer['name']} joined (user {entry['user']}). Try: arachne run {newcomer['name']} -- hostname")
        if missed:
            print(f"      {', '.join(missed)} could not be told right now; run `arachne sync` once they are online")

    server = invite_server(me["ip"], token, on_join)
    url = f"http://{me['ip']}:{server.server_address[1]}/{token}"
    print("Paste ONE of these on each device you want to add:\n")
    print("  macOS / Linux:")
    print(f"    curl -fsSL {REPO_RAW}/install.sh | sh -s -- --join {url}\n")
    print("  Windows (administrator PowerShell):")
    print(f"    & ([scriptblock]::Create((irm {REPO_RAW}/install.ps1))) -Join {url}\n")
    print("  arachne already installed there:")
    print(f"    arachne setup --join {url}\n")
    print(f"Sign in to Tailscale with the same account when asked. Waiting for devices ({INVITE_MINUTES} min, Ctrl-C to stop)...")
    server.timeout = 1
    deadline = time.time() + INVITE_MINUTES * 60
    try:
        while time.time() < deadline:
            server.handle_request()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def join(url: str) -> str:
    """Answer an invite: hand over this device's username and key, take everyone else's. Returns our name."""
    request = urllib.request.Request(
        url, data=json.dumps(agent.my_entry()).encode(), headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            answer = json.loads(response.read())
    except urllib.error.HTTPError as e:
        try:
            reason = json.loads(e.read()).get("error", str(e))
        except ValueError:
            reason = str(e)
        raise Error(f"the invite was refused: {reason}") from None
    except (urllib.error.URLError, OSError, ValueError):
        raise Error(
            "could not reach the inviting device. Check that Tailscale is connected on both, and that "
            "`arachne invite` is still waiting there (run it again for a fresh line)"
        ) from None
    agent.merge_peers(answer["peers"])
    return f"paired with {answer['inviter']} and {len(answer['peers']) - 1} other device(s) as {answer['name']}"


def sync() -> int:
    """Make every online device know every other one (after devices were offline during an invite)."""
    online = [d for d in devices(tailscale_status()) if d["online"]]
    known: dict = {}
    reached = []
    for dev in online:
        try:
            info = remote.call_json(dev, "peers-get", timeout=20)
        except Error as e:
            print(f"  !!  {e}", file=sys.stderr)
            continue
        reached.append(dev)
        for name, entry in info["peers"].items():
            known.setdefault(name, entry)
        known[dev["name"]] = info["self"]  # a device's own word about itself wins
    missed = announce(known, reached)
    for dev in reached:
        if dev["name"] not in missed:
            print(f"  ok  {dev['name']} knows {len(known)} device(s)")
    return 0 if len(reached) == len(online) and not missed else 1


def doctor() -> int:
    """Check this device, then whether each other device can be reached, and say how to fix what is wrong."""
    from arachne import provision

    problems = 0

    def check(ok: bool, good: str, fix: str) -> None:
        nonlocal problems
        problems += not ok
        print(f"  {'ok ' if ok else '!! '} {good if ok else fix}")

    print(f"This device (arachne {__version__})")
    status = tailscale_status(require_running=False)
    connected = status.get("BackendState") == "Running"
    check(connected, "Tailscale is connected", "Tailscale is not connected: open the Tailscale app or run `tailscale up`")
    check(provision.ssh_listening(), "SSH server is running", "SSH server is off, so other devices cannot reach this one: run `arachne setup`")
    bridge = desktop.bridge_state()
    check(bridge["installed"], "agent-desktop is installed", "agent-desktop is missing (desktop control): run `arachne setup`")
    check(bridge["running"], "desktop bridge is running", "desktop bridge is not running: sign in to the desktop and run `arachne setup`")
    if not connected:
        return 1

    print("\nOther devices")
    others = [d for d in devices(status) if not d["self"]]
    if not others:
        print("  none yet: run `arachne invite` and paste the line it prints on another device")
    for dev in others:
        if not dev["online"]:
            print(f"  --  {dev['name']}: offline")
            continue
        try:
            started = time.time()
            info = remote.call_json(dev, "peers-get", timeout=20)
            check(True, f"{dev['name']}: reachable as {info['self']['user']} ({(time.time() - started) * 1000:.0f} ms, {dev['link']})", "")
        except Error as e:
            check(False, "", str(e))
    return 1 if problems else 0
