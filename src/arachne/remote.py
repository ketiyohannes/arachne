"""Controller side: reach a device over SSH and invoke the arachne installed there.

Every device runs the same package, so the controller sends one opaque, shell-safe
argument (`arachne _ VERB BASE64-JSON`) instead of fighting the quoting rules of
sh, cmd.exe and PowerShell. The local device is called directly, without SSH.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys

from arachne.core import NO_WINDOW, Error, load_config, state_dir

# cmd.exe refuses command lines over 8191 characters.
WINDOWS_PAYLOAD_LIMIT = 7000


def actor() -> str:
    """Who is driving: an AI agent's name when one is detected, otherwise 'you'. Shown in the dashboard trace."""
    if os.environ.get("ARACHNE_ACTOR"):
        return os.environ["ARACHNE_ACTOR"]
    if os.environ.get("CLAUDECODE"):
        return "claude-code"
    if os.environ.get("CODEX_SANDBOX") or os.environ.get("CODEX_HOME"):
        return "codex"
    return "you" if sys.stdin.isatty() else "script"


def encode(payload: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def decode(text: str) -> dict:
    return json.loads(base64.urlsafe_b64decode(text.encode()))


def ssh_user(dev: dict, user: str | None = None) -> str | None:
    return user or (load_config().get("peers") or {}).get(dev["name"], {}).get("user")


def ssh_options(batch: bool) -> list[str]:
    """Options shared by ssh and scp.

    Tailscale already authenticates the peer behind each 100.x address, so new host
    keys are accepted automatically; a *changed* key is still rejected.
    """
    opts = ["-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10"]
    if batch:
        opts += ["-o", "BatchMode=yes"]  # fail instead of hanging on a password prompt
    if os.name != "nt":
        # Reuse one connection per device: repeat commands and dashboard polls become instant.
        opts += ["-o", "ControlMaster=auto", "-o", f"ControlPath={state_dir()}/cm-%C", "-o", "ControlPersist=120"]
    return opts


def ssh_target(dev: dict, user: str | None = None) -> str:
    user = ssh_user(dev, user)
    return f"{user}@{dev['ip']}" if user else dev["ip"]


def ssh_argv(dev: dict, remote_command: str | None, user: str | None = None, tty: bool = False) -> list[str]:
    ssh = shutil.which("ssh")
    if not ssh:
        raise Error("ssh is not installed")
    argv = [ssh, *ssh_options(batch=not tty)]
    if tty:
        argv.append("-t")
    argv.append(ssh_target(dev, user))
    if remote_command:
        argv.append(remote_command)
    return argv


def remote_invocation(dev: dict, verb: str, payload: dict) -> str:
    """The command line that runs `arachne _ VERB PAYLOAD` on a device, whatever its login shell."""
    blob = encode(payload)
    if dev["os"] == "windows":
        if len(blob) > WINDOWS_PAYLOAD_LIMIT:
            raise Error("command is too long for a Windows device; put it in a script, `arachne cp` it over and run that")
        # `cmd /c` expands %USERPROFILE% under both cmd.exe and PowerShell default shells.
        return f'cmd /c "%USERPROFILE%\\.local\\bin\\arachne.exe" _ {verb} {blob}'
    return f'"$HOME/.local/bin/arachne" _ {verb} {blob}'


def call_argv(dev: dict, verb: str, payload: dict, user: str | None = None, tty: bool = False) -> list[str]:
    if dev["self"]:
        return [sys.executable, "-m", "arachne", "_", verb, encode(payload)]
    return ssh_argv(dev, remote_invocation(dev, verb, payload), user, tty)


def call(dev: dict, verb: str, payload: dict | None = None, user: str | None = None) -> int:
    """Run a device-side verb with this terminal's stdin/stdout attached; return its exit code."""
    tty = sys.stdin.isatty() and sys.stdout.isatty()
    code = subprocess.run(call_argv(dev, verb, payload or {}, user, tty)).returncode
    if not dev["self"]:
        explain_failure(dev, code)
    return code


def call_json(dev: dict, verb: str, payload: dict | None = None, user: str | None = None, timeout: float = 30):
    """Run a device-side verb that prints JSON and return the parsed result."""
    try:
        proc = subprocess.run(
            call_argv(dev, verb, payload or {}, user),
            capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        raise Error(f"{dev['name']}: no answer within {timeout:.0f}s") from None
    try:
        return json.loads(proc.stdout)
    except ValueError:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        raise Error(f"{dev['name']}: {failure_hint(dev, proc.returncode) or (detail[-1] if detail else 'no output')}") from None


def failure_hint(dev: dict, code: int) -> str | None:
    if code == 255:
        return (
            f"could not open an SSH session to {dev['name']} ({dev['ip']}). If it was never paired with this device, "
            f"run `arachne invite` here and paste the line on {dev['name']}; otherwise run `arachne doctor`"
        )
    if code in (127, 9009):  # sh and cmd.exe "command not found"
        return f"arachne is not installed on {dev['name']} (run the installer there, or use `arachne run --raw`)"
    return None


def explain_failure(dev: dict, code: int) -> None:
    hint = failure_hint(dev, code)
    if hint:
        print(f"arachne: exit {code}. If that did not come from your command: {hint}", file=sys.stderr)
