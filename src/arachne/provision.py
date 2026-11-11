"""`arachne setup`: turn the machine it runs on into a device every other device can use.

Each step delegates to the platform's own tooling (Tailscale, OpenSSH, launchd,
XDG autostart, the Windows Run key, npm/brew) and is safe to repeat.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import socket
import subprocess
import sys
from importlib import resources
from pathlib import Path

from arachne import agent, desktop
from arachne.core import (
    Error,
    devices,
    load_config,
    save_config,
    state_dir,
    tailscale_bin,
    tailscale_status,
)

BRIDGE_LABEL = "dev.arachne.bridge"


def say(ok: bool, message: str) -> None:
    print(f"  {'ok ' if ok else '!! '} {message}")


def run(argv: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, **kwargs)


def sudo(argv: list[str]) -> bool:
    """Run with sudo, letting it prompt on the terminal."""
    return subprocess.run(["sudo", *argv]).returncode == 0


def ssh_listening() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 22), timeout=2):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------- steps


def ensure_tailscale() -> dict | None:
    try:
        binary = tailscale_bin()
    except Error:
        say(False, "Tailscale is not installed: get it from https://tailscale.com/download, sign in, re-run `arachne setup`")
        return None
    status = tailscale_status(require_running=False)
    if status.get("BackendState") != "Running":
        print("  ..  connecting to Tailscale (a browser sign-in may open; use the same account on every device)")
        up = [binary, "up"]
        subprocess.run(["sudo", *up] if sys.platform.startswith("linux") and os.geteuid() != 0 else up)
        status = tailscale_status(require_running=False)
    if status.get("BackendState") != "Running":
        say(False, "Tailscale is not connected: open the Tailscale app (or `tailscale up`), sign in, re-run `arachne setup`")
        return None
    me = next(d for d in devices(status) if d["self"])
    say(True, f"Tailscale connected as {me['name']} ({me['ip']})")
    return me


def enable_ssh_server() -> bool:
    if ssh_listening():
        say(True, "SSH server is running")
        return True
    print("  ..  turning on the SSH server (may ask for your password)")
    if sys.platform == "darwin":
        sudo(["systemsetup", "-setremotelogin", "on"]) and ssh_listening() or sudo(
            ["launchctl", "load", "-w", "/System/Library/LaunchDaemons/ssh.plist"]
        )
        manual = "System Settings > General > Sharing > Remote Login"
    elif os.name == "nt":
        script = (
            "Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 | Out-Null; "
            "Set-Service -Name sshd -StartupType Automatic; Start-Service sshd"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", script])
        manual = "an administrator PowerShell: Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0; Start-Service sshd"
    else:
        if not shutil.which("sshd") and not Path("/usr/sbin/sshd").exists():
            for manager, install in (
                ("apt-get", ["apt-get", "install", "-y", "openssh-server"]),
                ("dnf", ["dnf", "install", "-y", "openssh-server"]),
                ("pacman", ["pacman", "-S", "--noconfirm", "openssh"]),
                ("zypper", ["zypper", "install", "-y", "openssh"]),
            ):
                if shutil.which(manager):
                    sudo(install)
                    break
        sudo(["systemctl", "enable", "--now", "ssh"]) or sudo(["systemctl", "enable", "--now", "sshd"])
        manual = "your distribution's openssh-server package"
    ok = ssh_listening()
    say(ok, "SSH server is running" if ok else f"could not turn on the SSH server; enable it via {manual}")
    return ok


def ensure_agent_desktop() -> str | None:
    binary = shutil.which("agent-desktop")
    if not binary:
        print("  ..  installing agent-desktop (desktop control)")
        if shutil.which("npm"):
            subprocess.run(["npm", "install", "-g", "agent-desktop"], shell=os.name == "nt")
        elif shutil.which("brew"):
            subprocess.run(["brew", "install", "agent-desktop"])
        binary = shutil.which("agent-desktop")
    if not binary:
        say(False, "agent-desktop is missing: install Node.js, run `npm install -g agent-desktop`, re-run `arachne setup`")
        return None
    config = load_config()
    config.update(agent_desktop=binary, path=os.environ.get("PATH", ""))
    save_config(config)
    say(True, f"agent-desktop installed ({binary})")
    return binary


def bridge_command() -> list[str]:
    python = Path(sys.executable)
    windowless = python.with_name("pythonw.exe")  # no console window on Windows
    return [str(windowless if windowless.exists() else python), "-m", "arachne", "desktop-bridge"]


def start_detached(argv: list[str]) -> None:
    kwargs: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(argv, **kwargs)


def install_bridge() -> bool:
    """Start the desktop bridge now and at every login, inside the user's desktop session."""
    command = bridge_command()
    if sys.platform == "darwin":
        plist = Path.home() / "Library" / "LaunchAgents" / f"{BRIDGE_LABEL}.plist"
        plist.parent.mkdir(parents=True, exist_ok=True)
        plist.write_bytes(plistlib.dumps({
            "Label": BRIDGE_LABEL,
            "ProgramArguments": command,
            "RunAtLoad": True,
            "KeepAlive": True,
            "LimitLoadToSessionType": "Aqua",  # only inside a real desktop login
            "StandardErrorPath": str(state_dir() / "bridge.log"),
        }))
        domain = f"gui/{os.getuid()}"
        run(["launchctl", "bootout", f"{domain}/{BRIDGE_LABEL}"])
        result = run(["launchctl", "bootstrap", domain, str(plist)])
        ok = result.returncode == 0
        say(ok, "desktop bridge starts at login" if ok else f"could not start the desktop bridge: {result.stderr.strip()}")
        return ok
    if os.name == "nt":
        value = subprocess.list2cmdline(command)
        key = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run"
        ok = run(["reg", "add", key, "/v", "ArachneBridge", "/t", "REG_SZ", "/d", value, "/f"]).returncode == 0
    else:
        entry = Path.home() / ".config" / "autostart" / "arachne-bridge.desktop"
        entry.parent.mkdir(parents=True, exist_ok=True)
        exec_line = " ".join(f'"{part}"' for part in command)
        entry.write_text(f"[Desktop Entry]\nType=Application\nName=arachne desktop bridge\nExec={exec_line}\nNoDisplay=true\n")
        ok = True
    in_desktop = os.name == "nt" or bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    if ok and in_desktop and not desktop.bridge_state()["running"]:
        start_detached(command)
    say(ok, "desktop bridge starts at login" + ("" if in_desktop else " (sign in to the desktop to start it)"))
    return ok


def skill_text() -> str:
    return resources.files("arachne").joinpath("skill/SKILL.md").read_text()


def install_skill(directory: str | None = None) -> Path:
    target = Path(directory).expanduser() if directory else Path.home() / ".claude" / "skills" / "arachne"
    target.mkdir(parents=True, exist_ok=True)
    (target / "SKILL.md").write_text(skill_text())
    return target


# ---------------------------------------------------------------------------- commands


def setup(keys: list[str], with_desktop: bool = True, join_url: str | None = None) -> int:
    from arachne import pairing

    print("arachne setup")
    me = ensure_tailscale()
    ssh_ok = enable_ssh_server()
    agent.own_public_key()
    for key in keys:
        agent.authorize_key(key)
        say(True, "authorized the given SSH key")
    paired = True
    if join_url and me:
        try:
            say(True, pairing.join(join_url))
        except Error as e:
            paired = False
            say(False, str(e))
    desktop_ok = True
    if with_desktop:
        desktop_ok = bool(ensure_agent_desktop()) and install_bridge()
    if (Path.home() / ".claude").is_dir():
        say(True, f"agent skill installed in {install_skill()}")

    ready = bool(me and ssh_ok and desktop_ok and paired)
    print("\nThis device is ready." if ready else "\nNot finished: fix the lines marked !! above and run `arachne setup` again.")
    if ready and not join_url:
        print("To add another device, run `arachne invite` here and paste the line it prints on that device.")
    if with_desktop and sys.platform == "darwin" and me:
        print(f"For desktop control on this Mac, grant permissions once: arachne desktop {me['name']} permissions --guide")
    return 0 if ready else 1
