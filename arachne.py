"""arachne: run terminal commands on your Tailscale devices over SSH.

    arachne ls                         list devices on your tailnet
    arachne run HOST                   open a shell on HOST
    arachne run HOST -- COMMAND...     run a command on HOST and exit with its exit code
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

__version__ = "0.2.0"

TAILSCALE_PATHS = (
    "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
    r"C:\Program Files\Tailscale\tailscale.exe",
)


class Error(Exception):
    """A problem to report to the user (no traceback)."""


# ---------------------------------------------------------------------------- tailscale


def tailscale_bin() -> str:
    found = shutil.which("tailscale")
    if found:
        return found
    for path in TAILSCALE_PATHS:
        if os.path.exists(path):
            return path
    raise Error("tailscale is not installed (https://tailscale.com/download)")


def tailscale_status() -> dict:
    proc = subprocess.run([tailscale_bin(), "status", "--json"], capture_output=True, text=True)
    try:
        status = json.loads(proc.stdout)
    except ValueError:
        raise Error(f"could not read tailscale status: {(proc.stderr or proc.stdout).strip()}") from None
    state = status.get("BackendState")
    if state != "Running":
        raise Error(f"tailscale is not connected (state: {state}); run `tailscale up` or open the Tailscale app")
    return status


def devices(status: dict) -> list[dict]:
    """Every device on the tailnet, this machine included, as simple dicts."""
    out = []
    peers = [(status["Self"], True)] + [(p, False) for p in (status.get("Peer") or {}).values()]
    for node, is_self in peers:
        dns = (node.get("DNSName") or "").rstrip(".")
        ips = node.get("TailscaleIPs") or []
        out.append({
            "name": dns.split(".")[0] if dns else node.get("HostName", ""),
            "hostname": node.get("HostName", ""),
            "dns": dns,
            "ip": ips[0] if ips else "",
            "os": node.get("OS", ""),
            "online": True if is_self else bool(node.get("Online")),
            "self": is_self,
        })
    return sorted(out, key=lambda d: (not d["online"], d["name"].lower()))


def find_device(devs: list[dict], query: str) -> dict:
    """Match by MagicDNS name, full DNS name, hostname or Tailscale IP (case-insensitive)."""
    q = query.lower().rstrip(".")
    exact = [d for d in devs if q in (d["name"].lower(), d["dns"].lower(), d["hostname"].lower(), d["ip"])]
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


# ---------------------------------------------------------------------------- commands


def ssh_argv(dev: dict, command: list[str], user: str | None, tty: bool) -> list[str]:
    ssh = shutil.which("ssh")
    if not ssh:
        raise Error("ssh is not installed")
    target = f"{user}@{dev['ip']}" if user else dev["ip"]
    argv = [ssh]
    if command and tty:
        argv.append("-t")  # interactive programs (top, vim) need a terminal
    return argv + [target] + command


def cmd_ls(args: argparse.Namespace) -> int:
    devs = devices(tailscale_status())
    if not args.all:
        devs = [d for d in devs if d["online"]]
    if args.json:
        print(json.dumps(devs, indent=2))
        return 0
    if not devs:
        print("no online devices (use --all to include offline ones)")
        return 0
    rows = [("NAME", "IP", "OS", "STATUS")] + [
        (d["name"] + (" (this)" if d["self"] else ""), d["ip"], d["os"], "online" if d["online"] else "offline")
        for d in devs
    ]
    widths = [max(len(r[i]) for r in rows) for i in range(4)]
    for r in rows:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip())
    return 0


def cmd_run(args: argparse.Namespace, command: list[str]) -> int:
    dev = find_device(devices(tailscale_status()), args.host)
    if not dev["online"]:
        raise Error(f"{dev['name']} is offline in Tailscale")
    argv = ssh_argv(dev, command, args.user, sys.stdin.isatty() and sys.stdout.isatty())
    if os.name != "nt":
        os.execv(argv[0], argv)  # hand the terminal to ssh; its exit code becomes ours
    return subprocess.run(argv).returncode


# ---------------------------------------------------------------------------- entry point


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="arachne", description="Run terminal commands on your Tailscale devices over SSH.")
    p.add_argument("--version", action="version", version=f"arachne {__version__}")
    sub = p.add_subparsers(dest="cmd", metavar="COMMAND", required=True)

    ls = sub.add_parser("ls", help="list devices on your tailnet")
    ls.add_argument("-a", "--all", action="store_true", help="include offline devices")
    ls.add_argument("--json", action="store_true", help="machine-readable output")

    run = sub.add_parser("run", help="open a shell on a device, or run a command after --")
    run.add_argument("host", help="device name, hostname or Tailscale IP (unique prefixes work)")
    run.add_argument("-u", "--user", help="remote user (default: from ~/.ssh/config, else your username)")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    command: list[str] = []
    if "--" in argv:
        i = argv.index("--")
        argv, command = argv[:i], argv[i + 1 :]
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "ls":
            if command:
                raise Error("ls takes no command")
            return cmd_ls(args)
        return cmd_run(args, command)
    except Error as e:
        print(f"arachne: {e}", file=sys.stderr)
        return 1


def main_exit() -> None:
    sys.exit(main())


if __name__ == "__main__":
    main_exit()
