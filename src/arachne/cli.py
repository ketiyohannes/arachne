"""arachne: one CLI for all your devices over Tailscale.

    arachne devices                          list devices on your tailnet
    arachne run HOST -- COMMAND              run a command (exit code passes through)
    arachne run HOST --detach -- COMMAND     start a long job; follow it with jobs / logs / kill
    arachne cp SRC... DST                    copy files; either side may be DEVICE:PATH
    arachne desktop HOST ARGS...             drive the device's desktop (agent-desktop)
    arachne stats [HOST]                     CPU, memory, GPU, jobs
    arachne dashboard                        web dashboard of every device
    arachne invite                           add a device (paste the printed line on it)
    arachne doctor                           check that everything is connected
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import shlex
import shutil
import subprocess
import sys

from arachne import __version__, agent, desktop, pairing, provision, remote
from arachne.core import (
    Error,
    devices,
    find_device,
    load_config,
    resolve,
    save_config,
    tailscale_status,
)

# ---------------------------------------------------------------------------- helpers


def table(rows: list[tuple]) -> None:
    widths = [max(len(str(r[i])) for r in rows) for i in range(len(rows[0]))]
    for row in rows:
        print("  ".join(str(c).ljust(w) for c, w in zip(row, widths)).rstrip())


def command_line(dev: dict, words: list[str]) -> str:
    """One word is taken as a full command line; several are quoted for the device's shell."""
    if len(words) == 1:
        return words[0]
    return subprocess.list2cmdline(words) if dev["os"] == "windows" else shlex.join(words)


def parse_env(pairs: list[str]) -> dict:
    env = {}
    for pair in pairs:
        if "=" not in pair:
            raise Error(f"--env expects KEY=VALUE, got '{pair}'")
        key, value = pair.split("=", 1)
        env[key] = value
    return env


def ago(timestamp: float | None) -> str:
    if not timestamp:
        return "-"
    seconds = int(datetime.datetime.now().timestamp() - timestamp)
    for size, unit in ((86400, "d"), (3600, "h"), (60, "m")):
        if seconds >= size:
            return f"{seconds // size}{unit} ago"
    return f"{max(seconds, 0)}s ago"


# ---------------------------------------------------------------------------- commands


def cmd_devices(args, command) -> int:
    devs = devices(tailscale_status())
    if not args.all:
        devs = [d for d in devs if d["online"]]
    if args.json:
        print(json.dumps(devs, indent=2))
        return 0
    rows = [("NAME", "IP", "OS", "STATUS", "LINK")] + [
        (d["name"] + (" (this)" if d["self"] else ""), d["ip"], d["os"], "online" if d["online"] else "offline", d["link"])
        for d in devs
    ]
    table(rows)
    return 0


def cmd_run(args, command) -> int:
    if not command:
        raise Error("nothing to run: arachne run HOST -- COMMAND (or `arachne ssh HOST` for a shell)")
    dev = resolve(args.host)
    line = command_line(dev, command)
    if args.raw:
        if args.detach or args.cwd or args.env:
            raise Error("--raw sends the command straight to ssh; --detach, --cwd and --env need arachne on the device")
        if dev["self"]:
            return subprocess.run(agent.shell_argv(line)).returncode
        tty = sys.stdin.isatty() and sys.stdout.isatty()
        return subprocess.run(remote.ssh_argv(dev, line, args.user, tty)).returncode
    payload = {"command": line, "cwd": args.cwd, "env": parse_env(args.env), "actor": remote.actor()}
    if args.detach:
        job = remote.call_json(dev, "job-start", {**payload, "name": args.name}, args.user)
        print(f"started job {job['id']} on {dev['name']}" + (f" ({job['name']})" if job["name"] != job["id"] else ""))
        print(f"  follow: arachne logs {dev['name']} {job['id']} -f")
        return 0
    return remote.call(dev, "exec", payload, args.user)


def cmd_ssh(args, command) -> int:
    dev = resolve(args.host)
    if dev["self"]:
        raise Error("that is this device; you already have a shell here")
    argv = remote.ssh_argv(dev, None, args.user, tty=True)
    if os.name != "nt":
        os.execv(argv[0], argv)
    return subprocess.run(argv).returncode


def split_endpoint(text: str, devs: list[dict]) -> tuple[dict | None, str]:
    """'DEVICE:PATH' -> (device, path); anything else (including C:\\paths) is a local path."""
    name, sep, path = text.partition(":")
    if not sep or len(name) < 2 or "/" in name or "\\" in name:
        return None, text
    dev = find_device(devs, name)
    if not dev["online"]:
        raise Error(f"{dev['name']} is offline in Tailscale")
    return (None, path or ".") if dev["self"] else (dev, path)


def cmd_cp(args, command) -> int:
    scp = shutil.which("scp")
    if not scp:
        raise Error("scp is not installed")
    devs = devices(tailscale_status())
    endpoints = [split_endpoint(p, devs) for p in args.paths]
    if len(endpoints) < 2:
        raise Error("usage: arachne cp SRC... DST  (either side may be DEVICE:PATH)")
    scp_args = []
    for dev, path in endpoints:
        scp_args.append(f"{remote.ssh_target(dev, args.user)}:{path or '.'}" if dev else path)
    remote_sources = [dev for dev, _ in endpoints[:-1] if dev]
    argv = [scp, "-p", *remote.ssh_options(batch=not sys.stdin.isatty())]
    if args.recursive:
        argv.append("-r")
    if remote_sources and endpoints[-1][0]:
        argv.append("-3")  # device to device: relay through this machine, so the two need not trust each other
    code = subprocess.run([*argv, *scp_args]).returncode
    if code == 0:
        print(f"copied {len(endpoints) - 1} item(s) to {args.paths[-1]}")
    return code


def job_targets(host: str | None) -> list[dict]:
    if host:
        return [resolve(host)]
    return [d for d in devices(tailscale_status()) if d["online"]]


def cmd_jobs(args, command) -> int:
    found, errors = [], []
    for dev in job_targets(args.host):
        try:
            found += [{**job, "device": dev["name"]} for job in remote.call_json(dev, "job-list", None, args.user)]
        except Error as e:
            errors.append(str(e))
    if args.json:
        print(json.dumps(found, indent=2))
    elif found:
        table([("DEVICE", "JOB", "NAME", "STATUS", "STARTED", "COMMAND")] + [
            (j["device"], j["id"], j["name"], j["status"], ago(j["started"]), j["command"][:60]) for j in found
        ])
    else:
        print("no jobs")
    for error in errors:
        print(f"arachne: {error}", file=sys.stderr)
    return 0 if not errors or found else 1


def cmd_logs(args, command) -> int:
    payload = {"id": args.job, "follow": args.follow, "tail": args.tail}
    return remote.call(resolve(args.host), "job-logs", payload, args.user)


def cmd_kill(args, command) -> int:
    return remote.call(resolve(args.host), "job-kill", {"id": args.job}, args.user)


def cmd_desktop(argv: list[str]) -> int:
    """arachne desktop HOST [-o FILE] AGENT-DESKTOP-ARGS...  (everything after HOST goes to agent-desktop)."""
    if len(argv) < 2 or argv[0] in ("-h", "--help"):
        print(
            "usage: arachne desktop HOST [-o FILE] COMMAND [ARGS...]\n\n"
            "Runs agent-desktop on HOST's desktop and prints its JSON answer. Start with:\n"
            "  arachne desktop HOST skills get desktop     the guide: snapshot / act / verify loop\n"
            "  arachne desktop HOST status                 permissions and platform\n"
            "  arachne desktop HOST snapshot --app NAME -i\n"
            "  arachne desktop HOST -o shot.png screenshot  save a screenshot on THIS machine\n"
            "Pipe text on stdin for commands that take --stdin (e.g. type)."
        )
        return 0 if len(argv) >= 1 else 2
    host, rest = argv[0], argv[1:]
    out_path = None
    if rest[0] in ("-o", "--out"):
        if len(rest) < 3:
            raise Error("usage: arachne desktop HOST -o FILE screenshot [ARGS...]")
        out_path, rest = rest[1], rest[2:]
    stdin = sys.stdin.read() if "--stdin" in rest else None
    payload = {"args": rest, "stdin": stdin, "actor": remote.actor()}
    result = remote.call_json(resolve(host), "desktop", payload, timeout=desktop.RUN_TIMEOUT + 20)
    return desktop.print_result(result, out_path)


def cmd_stats(args, command) -> int:
    targets = job_targets(args.host)
    results = {}
    for dev in targets:
        try:
            results[dev["name"]] = remote.call_json(dev, "stats", None, args.user)
        except Error as e:
            results[dev["name"]] = {"error": str(e)}
    if args.json:
        print(json.dumps(results, indent=2))
        return 0
    rows = [("DEVICE", "CPU", "MEMORY", "DISK", "GPU", "JOBS", "DESKTOP")]
    for name, s in results.items():
        if "error" in s:
            rows.append((name, "unreachable", "", "", "", "", ""))
            continue
        gpus = ", ".join(
            f"{g['name']} {g['util']:.0f}% {g['mem_used_mb'] / 1024:.1f}/{g['mem_total_mb'] / 1024:.0f}GB"
            for g in s["gpus"] if g["util"] is not None and g["mem_total_mb"]
        ) or "-"
        running = sum(1 for j in s["jobs"] if j["status"] == "running")
        rows.append((
            name, f"{s['cpu']['percent']:.0f}% of {s['cpu']['cores']}",
            f"{s['memory']['used_gb']}/{s['memory']['total_gb']}GB", f"{s['disk']['percent']:.0f}%", gpus,
            f"{running} running", "ready" if s["desktop"]["running"] else "off",
        ))
    table(rows)
    for name, s in results.items():
        if "error" in s:
            print(f"arachne: {s['error']}", file=sys.stderr)
    return 0


def cmd_dashboard(args, command) -> int:
    from arachne import dashboard

    return dashboard.serve(args.port, args.tailnet, args.interval, args.open)


def cmd_setup(args, command) -> int:
    return provision.setup(args.key, with_desktop=not args.no_desktop, join_url=args.join)


def cmd_invite(args, command) -> int:
    return pairing.invite()


def cmd_sync(args, command) -> int:
    return pairing.sync()


def cmd_doctor(args, command) -> int:
    return pairing.doctor()


def cmd_user(args, command) -> int:
    dev = find_device(devices(tailscale_status()), args.device)
    config = load_config()
    config.setdefault("peers", {}).setdefault(dev["name"], {})["user"] = args.name
    save_config(config)
    print(f"will connect to {dev['name']} as {args.name}")
    return 0


def cmd_skill(args, command) -> int:
    if args.action == "install":
        print(f"installed the arachne skill in {provision.install_skill(args.dir)}")
    else:
        print(provision.skill_text())
    return 0


def cmd_bridge(args, command) -> int:
    desktop.serve_bridge(args.port)
    return 0


# ---------------------------------------------------------------------------- device-side entry (`arachne _ VERB PAYLOAD`)

VERBS = {
    "exec": agent.verb_exec,
    "job-start": agent.verb_job_start,
    "job-list": agent.verb_job_list,
    "job-logs": agent.verb_job_logs,
    "job-kill": agent.verb_job_kill,
    "stats": agent.verb_stats,
    "output": agent.verb_output,
    "peers-get": agent.verb_peers_get,
    "peers-merge": agent.verb_peers_merge,
    "desktop": desktop.verb_desktop,
}


def internal(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "job-supervise":
        return agent.verb_job_supervise(argv[1])
    if len(argv) != 2 or argv[0] not in VERBS:
        raise Error("`arachne _` is the device-side protocol used by other arachne commands")
    return VERBS[argv[0]](remote.decode(argv[1]))


# ---------------------------------------------------------------------------- entry point


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="arachne", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--version", action="version", version=f"arachne {__version__}")
    sub = p.add_subparsers(dest="cmd", metavar="COMMAND", required=True)

    def add(name, func, help_text, user=False, **kwargs):
        parser = sub.add_parser(name, help=help_text, description=help_text, **kwargs)
        parser.set_defaults(func=func)
        if user:
            parser.add_argument("-u", "--user", help="remote username (default: `arachne user`, ~/.ssh/config, yours)")
        return parser

    ls = add("devices", cmd_devices, "list devices on your tailnet", aliases=["ls"])
    ls.add_argument("-a", "--all", action="store_true", help="include offline devices")
    ls.add_argument("--json", action="store_true", help="machine-readable output")

    run = add("run", cmd_run, "run a command on a device: arachne run HOST [options] -- COMMAND", user=True)
    run.add_argument("host", help="device name, hostname or Tailscale IP (unique prefixes work; 'self' is this device)")
    run.add_argument("-C", "--cwd", help="directory on the device to run in (default: home)")
    run.add_argument("-e", "--env", action="append", default=[], metavar="KEY=VALUE", help="extra environment variable")
    run.add_argument("-d", "--detach", action="store_true", help="start as a background job that survives disconnects")
    run.add_argument("-n", "--name", help="name for a detached job")
    run.add_argument("--raw", action="store_true", help="plain ssh, for devices without arachne installed")

    ssh = add("ssh", cmd_ssh, "open an interactive shell on a device", user=True)
    ssh.add_argument("host")

    cp = add("cp", cmd_cp, "copy files between devices: arachne cp SRC... DST, either side may be DEVICE:PATH", user=True)
    cp.add_argument("paths", nargs="+", metavar="PATH")
    cp.add_argument("-r", "--recursive", action="store_true", help="copy directories")

    jobs = add("jobs", cmd_jobs, "list detached jobs (on one device, or all)", user=True)
    jobs.add_argument("host", nargs="?")
    jobs.add_argument("--json", action="store_true")

    logs = add("logs", cmd_logs, "print a job's output", user=True)
    logs.add_argument("host")
    logs.add_argument("job", help="job id or name")
    logs.add_argument("-f", "--follow", action="store_true", help="stream until the job ends, then exit with its code")
    logs.add_argument("-t", "--tail", type=int, metavar="N", help="only the last N lines")

    kill = add("kill", cmd_kill, "stop a detached job", user=True)
    kill.add_argument("host")
    kill.add_argument("job")

    add("desktop", None, "drive a device's desktop: arachne desktop HOST ARGS... (see `arachne desktop --help`)")

    stats = add("stats", cmd_stats, "CPU, memory, disk, GPU and jobs (one device, or all)", user=True)
    stats.add_argument("host", nargs="?")
    stats.add_argument("--json", action="store_true")

    dash = add("dashboard", cmd_dashboard, "serve a live web dashboard of every device")
    dash.add_argument("-p", "--port", type=int, default=7777)
    dash.add_argument("--tailnet", action="store_true", help="also reachable from your other devices (default: this machine only)")
    dash.add_argument("--interval", type=float, default=5, help="seconds between refreshes")
    dash.add_argument("--open", action="store_true", help="open it in the browser")

    setup = add("setup", cmd_setup, "make this machine a device: Tailscale, SSH server, desktop bridge, agent skill")
    setup.add_argument("--join", metavar="URL", help="pair with the device that printed this invite link")
    setup.add_argument("--key", action="append", default=[], help="also accept this SSH public key (manual pairing)")
    setup.add_argument("--no-desktop", action="store_true", help="skip desktop control")

    add("invite", cmd_invite, "add devices: prints one line to paste on them, then pairs them automatically")
    add("sync", cmd_sync, "re-share usernames and keys between all online devices (rarely needed)")
    add("doctor", cmd_doctor, "check this device and the connection to every other one, with fixes")

    user = add("user", cmd_user, "override the username used on a device (normally learned when pairing)")
    user.add_argument("device")
    user.add_argument("name")

    skill = add("skill", cmd_skill, "print the agent skill, or install it for Claude Code")
    skill.add_argument("action", nargs="?", choices=["show", "install"], default="show")
    skill.add_argument("--dir", help="where to install (default: ~/.claude/skills/arachne)")

    bridge = add("desktop-bridge", cmd_bridge, "run the desktop bridge (normally started at login by `arachne setup`)")
    bridge.add_argument("--port", type=int, default=desktop.DEFAULT_PORT)
    return p


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        if argv[:1] == ["_"]:
            return internal(argv[1:])
        if argv[:1] == ["desktop"]:
            return cmd_desktop(argv[1:])
        command: list[str] = []
        if "--" in argv:
            i = argv.index("--")
            argv, command = argv[:i], argv[i + 1 :]
        args = build_parser().parse_args(argv)
        if command and args.cmd != "run":
            raise Error(f"`{args.cmd}` takes no command after --")
        return args.func(args, command)
    except Error as e:
        print(f"arachne: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


def main_exit() -> None:
    sys.exit(main())
