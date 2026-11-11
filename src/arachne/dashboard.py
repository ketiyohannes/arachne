"""`arachne dashboard`: a read-only web page showing every device and what it is doing.

A background thread polls `tailscale status` and each online device's `stats` verb
(over the same SSH path as every other command); the page fetches /api/state.
No accounts and no writes: it binds to this machine unless --tailnet is given.
"""

from __future__ import annotations

import json
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from urllib.parse import parse_qs

from arachne import remote
from arachne.core import Error, devices, find_device, tailscale_status


def name_callers(dev: dict, stats: dict, names_by_ip: dict) -> None:
    """Replace the caller IP on jobs and activity with a device name."""
    for entry in stats.get("jobs", []) + stats.get("activity", []):
        origin = entry.get("from") or "local"
        entry["from"] = dev["name"] if origin == "local" else names_by_ip.get(origin, origin)


def collect() -> dict:
    try:
        status = tailscale_status(require_running=False)
    except Error as e:
        return {"generated": time.time(), "error": str(e), "devices": []}
    devs = devices(status)
    names_by_ip = {ip: d["name"] for d in devs for ip in d["ips"]}

    def probe(dev: dict) -> dict:
        if not dev["online"]:
            return dev
        try:
            dev["stats"] = remote.call_json(dev, "stats", timeout=20)
            name_callers(dev, dev["stats"], names_by_ip)
        except Error as e:
            dev["error"] = str(e)
        return dev

    with ThreadPoolExecutor(max_workers=8) as pool:
        devs = list(pool.map(probe, devs))
    return {
        "generated": time.time(),
        "tailnet": (status.get("MagicDNSSuffix") or "").rstrip("."),
        "tailscale": status.get("BackendState"),
        "devices": devs,
    }


def fetch_output(query: dict) -> dict:
    """What one command or job printed, read from the device that ran it."""
    try:
        dev = find_device(devices(tailscale_status(require_running=False)), query["device"][0])
        payload = {"id": query["id"][0], "kind": query.get("kind", ["run"])[0]}
        return remote.call_json(dev, "output", payload, timeout=20)
    except (Error, KeyError) as e:
        return {"text": "", "error": str(e) if isinstance(e, Error) else "expected device and id"}


def serve(port: int, tailnet: bool, interval: float, open_browser: bool) -> int:
    page = resources.files("arachne").joinpath("dashboard.html").read_bytes()
    state = {"generated": 0, "devices": [], "starting": True}
    lock = threading.Lock()

    def poll() -> None:
        nonlocal state
        while True:
            fresh = collect()
            fresh["interval"] = interval
            with lock:
                state = fresh
            time.sleep(interval)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path, _, query = self.path.partition("?")
            if path == "/api/output":
                body, kind = json.dumps(fetch_output(parse_qs(query))).encode(), "application/json"
            elif path == "/api/state":
                with lock:
                    body, kind = json.dumps(state).encode(), "application/json"
            elif path in ("/", "/index.html"):
                body, kind = page, "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args) -> None:
            pass

    host = "127.0.0.1"
    if tailnet:
        me = next(d for d in devices(tailscale_status()) if d["self"])
        host = me["ip"]  # reachable from your tailnet only, never the LAN or the internet
    try:
        server = ThreadingHTTPServer((host, port), Handler)
    except OSError as e:
        raise Error(f"cannot listen on {host}:{port} ({e}); pick another with --port") from None
    threading.Thread(target=poll, daemon=True).start()
    url = f"http://{host}:{port}/"
    print(f"arachne dashboard: {url}  (Ctrl-C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0
