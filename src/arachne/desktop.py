"""Desktop control through agent-desktop (https://github.com/vercel-labs/agent-desktop).

An SSH session cannot touch the screen: Windows runs it in session 0, Linux gives it
no display, and macOS ties GUI permissions to the launching app. So each device runs
a small bridge *inside the signed-in user's desktop session* (started at login). The
bridge listens on 127.0.0.1 only, requires a per-device token readable only by that
user, and does exactly one thing: run `agent-desktop` with the arguments it is given.
"""

from __future__ import annotations

import base64
import hmac
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from arachne.core import NO_WINDOW, Error, load_config, state_dir, write_private

DEFAULT_PORT = 47631
RUN_TIMEOUT = 180
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def bridge_file():
    return state_dir() / "bridge.json"


def agent_desktop_bin() -> str | None:
    configured = load_config().get("agent_desktop")
    if configured and os.path.exists(configured):
        return configured
    return shutil.which("agent-desktop")


# ---------------------------------------------------------------------------- bridge (runs in the desktop session)


def run_agent_desktop(args: list[str], stdin: str | None) -> dict:
    binary = agent_desktop_bin()
    if not binary:
        return {"code": 127, "stdout": "", "stderr": "agent-desktop is not installed on this device (npm install -g agent-desktop)"}
    env = dict(os.environ)
    saved_path = load_config().get("path")
    if saved_path:  # login-item environments have a minimal PATH; reuse the one captured by `arachne setup`
        env["PATH"] = saved_path + os.pathsep + env.get("PATH", "")
    try:
        proc = subprocess.run(
            [binary, *args], input=stdin, capture_output=True, text=True, timeout=RUN_TIMEOUT, env=env,
            encoding="utf-8", errors="replace", creationflags=NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return {"code": 124, "stdout": "", "stderr": f"agent-desktop did not finish within {RUN_TIMEOUT}s"}
    except OSError as e:
        return {"code": 126, "stdout": "", "stderr": f"could not run agent-desktop: {e}"}
    return {"code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


def serve_bridge(port: int = DEFAULT_PORT) -> None:
    token = secrets.token_urlsafe(32)
    one_at_a_time = threading.Lock()  # two agents driving one screen at once only confuse each other

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:
            if not hmac.compare_digest(self.headers.get("X-Arachne-Token", ""), token):
                return self.reply(403, {"error": "bad token"})
            try:
                request = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                args = [str(a) for a in request["args"]]
            except (ValueError, KeyError, TypeError):
                return self.reply(400, {"error": "expected {args: [...], stdin?: str}"})
            with one_at_a_time:
                self.reply(200, run_agent_desktop(args, request.get("stdin")))

        def log_message(self, *args) -> None:
            pass

    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)  # preferred port taken: any free one
    write_private(bridge_file(), json.dumps({"port": server.server_address[1], "token": token, "pid": os.getpid()}))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            bridge_file().unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------- client (same device, e.g. from SSH)


def bridge_state() -> dict:
    import psutil

    try:
        info = json.loads(bridge_file().read_text())
    except (OSError, ValueError):
        return {"running": False, "installed": bool(agent_desktop_bin())}
    return {"running": psutil.pid_exists(info.get("pid", -1)), "installed": bool(agent_desktop_bin())}


def ask_bridge(args: list[str], stdin: str | None = None) -> dict:
    try:
        info = json.loads(bridge_file().read_text())
    except (OSError, ValueError):
        raise Error(
            "the desktop bridge is not running on this device. Sign in to its desktop and run `arachne setup` "
            "(or `arachne desktop-bridge` for a one-off)"
        ) from None
    request = urllib.request.Request(
        f"http://127.0.0.1:{info['port']}/",
        data=json.dumps({"args": args, "stdin": stdin}).encode(),
        headers={"Content-Type": "application/json", "X-Arachne-Token": info["token"]},
    )
    try:
        with urllib.request.urlopen(request, timeout=RUN_TIMEOUT + 10) as response:
            return json.loads(response.read())
    except (urllib.error.URLError, OSError) as e:
        raise Error(f"the desktop bridge on this device did not answer ({e}); is someone signed in to its desktop?") from None


def verb_desktop(payload: dict) -> int:
    from arachne import (
        agent,  # local import: agent imports this module for the snapshot
    )

    # Desktop actions go in the same activity log as commands, so the dashboard shows the whole trace.
    entry_id = secrets.token_hex(4)
    args = payload["args"]
    agent.log_activity({
        "id": entry_id, "ts": time.time(), "kind": "desktop", "from": agent.caller(), "actor": payload.get("actor"),
        "command": ("agent-desktop " + " ".join(args))[:300], "pid": os.getpid(),
    })
    code = 1
    try:
        result = ask_bridge(args, payload.get("stdin"))
        code = int(result.get("code", 1))
        # Screenshots come back as base64; keep only the readable start of each answer.
        agent.save_output(entry_id, (result.get("stdout", "")[:20_000] + result.get("stderr", "")).encode())
        print(json.dumps(result))
    finally:
        agent.log_activity({"id": entry_id, "end": time.time(), "exit": code})
    return 0


# ---------------------------------------------------------------------------- controller helpers


def extract_png(envelope) -> tuple[bytes | None, object]:
    """Find a base64 PNG inside an agent-desktop JSON envelope; return it and the envelope with it removed."""
    found: list[bytes] = []

    def walk(node):
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        if isinstance(node, str) and len(node) > 64 and not found:
            try:
                raw = base64.b64decode(node.split(",", 1)[-1], validate=True)
            except ValueError:
                return node
            if raw.startswith(PNG_MAGIC):
                found.append(raw)
                return "<saved to file>"
        return node

    stripped = walk(envelope)
    return (found[0] if found else None), stripped


def print_result(result: dict, out_path: str | None) -> int:
    """Print a bridge result as agent-desktop would have; with out_path, save the screenshot locally."""
    stdout = result.get("stdout", "")
    if out_path and result.get("code") == 0:
        try:
            png, stripped = extract_png(json.loads(stdout))
        except ValueError:
            png = None
        if png is None:
            raise Error("the device returned no image; run the command without -o to see its answer")
        with open(out_path, "wb") as f:
            f.write(png)
        stripped.setdefault("data", {})["path"] = os.path.abspath(out_path)
        stdout = json.dumps(stripped) + "\n"
    sys.stdout.write(stdout)
    sys.stderr.write(result.get("stderr", ""))
    return int(result.get("code", 1))
