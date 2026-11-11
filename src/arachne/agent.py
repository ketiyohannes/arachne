"""Device side: the verbs a controller invokes here as `arachne _ VERB PAYLOAD`.

Covers running commands, detached jobs with logs, a system snapshot for the
dashboard, and key authorization. Desktop control lives in desktop.py.
"""

from __future__ import annotations

import getpass
import json
import os
import platform
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

from arachne import __version__
from arachne.core import NO_WINDOW, Error, load_config, save_config, state_dir

ACTIVITY_MAX_BYTES = 512_000
OUTPUT_MAX_BYTES = 256_000  # per command; the tail is what matters when something fails
OUTPUT_KEEP = 300
KEY_PATTERN = re.compile(r"^(ssh-(ed25519|rsa)|ecdsa-sha2-nistp\d+|sk-[a-z0-9-]+@openssh\.com) [A-Za-z0-9+/=]+( .*)?$")


# ---------------------------------------------------------------------------- running commands


def shell_argv(command: str) -> list[str]:
    """Run a command line the way the device's user would: login shell on Unix, PowerShell on Windows."""
    if os.name == "nt":
        return ["powershell", "-NoProfile", "-Command", command]
    return [os.environ.get("SHELL") or "/bin/sh", "-lc", command]


def working_dir(cwd: str | None) -> str:
    path = Path(cwd).expanduser() if cwd else Path.home()
    if not path.is_dir():
        raise Error(f"no such directory on this device: {path}")
    return str(path)


def caller() -> str:
    """Tailscale IP of the device that asked (from sshd), or 'local'."""
    return (os.environ.get("SSH_CONNECTION") or "local").split()[0]


def log_activity(entry: dict) -> None:
    path = state_dir() / "activity.jsonl"
    try:
        if path.exists() and path.stat().st_size > ACTIVITY_MAX_BYTES:
            path.write_text("\n".join(path.read_text().splitlines()[-200:]) + "\n")
        with path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass  # the activity log is informational; never fail a command over it


def recent_activity(limit: int = 40) -> list[dict]:
    """Latest commands run here, newest first, with start and end records merged."""
    try:
        lines = (state_dir() / "activity.jsonl").read_text().splitlines()[-400:]
    except OSError:
        return []
    merged: dict[str, dict] = {}
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        merged.setdefault(entry["id"], {}).update(entry)
    out = []
    for entry in merged.values():
        if "command" not in entry:
            continue
        if "exit" not in entry and not psutil.pid_exists(entry.get("pid", -1)):
            entry["exit"] = None  # the runner vanished without recording a result
        out.append(entry)
    return sorted(out, key=lambda e: e.get("ts", 0), reverse=True)[:limit]


def runs_dir() -> Path:
    path = state_dir() / "runs"
    path.mkdir(exist_ok=True)
    return path


def save_output(entry_id: str, data: bytes) -> None:
    """Keep what a command printed, so the dashboard can show it. Oldest outputs are pruned."""
    try:
        (runs_dir() / f"{entry_id}.log").write_bytes(data[-OUTPUT_MAX_BYTES:])
        logs = sorted(runs_dir().glob("*.log"), key=lambda p: p.stat().st_mtime)
        for old in logs[:-OUTPUT_KEEP]:
            old.unlink()
    except OSError:
        pass


def run_recorded(argv: list[str], cwd: str, env: dict, entry_id: str) -> int:
    """Run with output going to the caller as usual, and a copy kept for the dashboard.

    On a terminal the command gets the terminal untouched (editors, prompts and colours
    keep working) and nothing is recorded.
    """
    if sys.stdout.isatty():
        return subprocess.run(argv, cwd=cwd, env=env).returncode
    proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    kept = bytearray()
    lock = threading.Lock()
    try:  # written as it arrives, so the dashboard can show a command that is still running
        live = (runs_dir() / f"{entry_id}.log").open("wb")
    except OSError:
        live = None

    def pump(source, sink) -> None:
        while True:
            chunk = os.read(source.fileno(), 65536)
            if not chunk:
                return
            try:
                sink.write(chunk)
                sink.flush()
            except (OSError, ValueError):
                pass  # the caller went away; keep draining so the command is not blocked
            with lock:
                kept.extend(chunk)
                del kept[:-OUTPUT_MAX_BYTES]
                if live:
                    try:
                        live.write(chunk)
                        live.flush()
                    except OSError:
                        pass

    pumps = [
        threading.Thread(target=pump, args=(proc.stdout, sys.stdout.buffer), daemon=True),
        threading.Thread(target=pump, args=(proc.stderr, sys.stderr.buffer), daemon=True),
    ]
    for thread in pumps:
        thread.start()
    code = proc.wait()
    for thread in pumps:
        thread.join(timeout=5)
    if live:
        live.close()
    save_output(entry_id, bytes(kept))  # trims an oversized log to its tail and prunes old ones
    return code


def verb_exec(payload: dict) -> int:
    command = payload["command"]
    entry_id = secrets.token_hex(4)
    log_activity({
        "id": entry_id, "ts": time.time(), "kind": "run", "from": caller(), "actor": payload.get("actor"),
        "command": command[:300], "pid": os.getpid(),
    })
    code = 1
    try:
        env = {**os.environ, **(payload.get("env") or {})}
        code = run_recorded(shell_argv(command), working_dir(payload.get("cwd")), env, entry_id)
    finally:
        log_activity({"id": entry_id, "end": time.time(), "exit": code})
    return code


def verb_output(payload: dict) -> int:
    """What a command (kind 'run') or a job (kind 'job') printed, as JSON for the dashboard."""
    if payload.get("kind") == "job":
        path = find_job(payload["id"]) / "log"
    else:
        entry_id = payload["id"]
        if not entry_id.isalnum():
            raise Error("bad id")
        path = runs_dir() / f"{entry_id}.log"
    try:
        data = path.read_bytes()
    except OSError:
        print(json.dumps({"text": "", "missing": True}))
        return 0
    limit = int(payload.get("bytes") or 60_000)
    print(json.dumps({"text": data[-limit:].decode("utf-8", "replace"), "truncated": len(data) > limit}))
    return 0


# ---------------------------------------------------------------------------- detached jobs


def jobs_dir() -> Path:
    path = state_dir() / "jobs"
    path.mkdir(exist_ok=True)
    return path


def read_job(job_dir: Path) -> dict:
    meta = json.loads((job_dir / "meta.json").read_text())
    if "exit" in meta:
        meta["status"] = "killed" if (job_dir / "killed").exists() else ("done" if meta["exit"] == 0 else "failed")
    elif psutil.pid_exists(meta.get("supervisor", -1)):
        meta["status"] = "running"
    elif "supervisor" not in meta and time.time() - meta["started"] < 15:
        meta["status"] = "running"  # the supervisor is still starting up
    else:
        meta["status"] = "lost"  # supervisor died (reboot, crash) before recording a result
    return meta


def write_job(job_dir: Path, meta: dict) -> None:
    tmp = job_dir / "meta.json.tmp"
    tmp.write_text(json.dumps(meta))
    os.replace(tmp, job_dir / "meta.json")


def find_job(job_id: str) -> Path:
    matches = [p for p in jobs_dir().iterdir() if p.name == job_id or json_name(p) == job_id]
    if not matches:
        raise Error(f"no job '{job_id}' on this device")
    return max(matches, key=lambda p: p.stat().st_mtime)


def json_name(job_dir: Path) -> str | None:
    try:
        return json.loads((job_dir / "meta.json").read_text()).get("name")
    except (OSError, ValueError):
        return None


def verb_job_start(payload: dict) -> int:
    job_id = secrets.token_hex(3)
    job_dir = jobs_dir() / job_id
    job_dir.mkdir()
    cwd = working_dir(payload.get("cwd"))
    meta = {
        "id": job_id, "name": payload.get("name") or job_id, "command": payload["command"], "cwd": cwd,
        "env": payload.get("env") or {}, "from": caller(), "actor": payload.get("actor"), "started": time.time(),
    }
    write_job(job_dir, meta)
    # The supervisor outlives this SSH session: its own session on Unix, a detached process on Windows.
    kwargs: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    argv = [sys.executable, "-m", "arachne", "_", "job-supervise", job_id]
    if os.name == "nt":
        detached = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        try:  # sshd puts sessions in a job object; break away so the job survives disconnect
            subprocess.Popen(argv, creationflags=detached | 0x01000000, **kwargs)
        except OSError:
            subprocess.Popen(argv, creationflags=detached, **kwargs)
    else:
        subprocess.Popen(argv, start_new_session=True, **kwargs)
    print(json.dumps({"id": job_id, "name": meta["name"], "log": str(job_dir / "log")}))
    return 0


def verb_job_supervise(job_id: str) -> int:
    """Run the job's command to completion, streaming output to its log and recording the exit code."""
    job_dir = jobs_dir() / job_id
    meta = json.loads((job_dir / "meta.json").read_text())
    meta["supervisor"] = os.getpid()
    write_job(job_dir, meta)
    with (job_dir / "log").open("ab") as log:
        try:
            child = subprocess.Popen(
                shell_argv(meta["command"]), cwd=meta["cwd"], env={**os.environ, **meta["env"]},
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, creationflags=NO_WINDOW,
            )
        except OSError as e:
            log.write(f"arachne: could not start: {e}\n".encode())
            meta.update(exit=127, ended=time.time())
            write_job(job_dir, meta)
            return 127
        meta["pid"] = child.pid
        write_job(job_dir, meta)
        code = child.wait()
    meta.update(exit=code, ended=time.time())
    write_job(job_dir, meta)
    return code


def list_jobs(limit: int | None = None) -> list[dict]:
    out = []
    for job_dir in jobs_dir().iterdir():
        try:
            out.append(read_job(job_dir))
        except (OSError, ValueError):
            continue
    out.sort(key=lambda j: j["started"], reverse=True)
    return out[:limit] if limit else out


def verb_job_list(payload: dict) -> int:
    print(json.dumps(list_jobs()))
    return 0


def verb_job_logs(payload: dict) -> int:
    job_dir = find_job(payload["id"])
    log_path = job_dir / "log"
    out = sys.stdout.buffer
    with log_path.open("rb") if log_path.exists() else open(os.devnull, "rb") as log:
        data = log.read()
        tail = payload.get("tail")
        if tail:
            data = b"\n".join(data.splitlines()[-tail:]) + (b"\n" if data else b"")
        out.write(data)
        out.flush()
        while payload.get("follow"):
            chunk = log.read()
            if chunk:
                out.write(chunk)
                out.flush()
            elif read_job(job_dir)["status"] != "running":
                break
            else:
                time.sleep(0.5)
    job = read_job(job_dir)
    if payload.get("follow") and job["status"] != "running":
        return job.get("exit") or 0
    return 0


def verb_job_kill(payload: dict) -> int:
    job_dir = find_job(payload["id"])
    job = read_job(job_dir)
    if job["status"] != "running":
        print(f"job {job['id']} is not running ({job['status']})")
        return 0
    (job_dir / "killed").touch()
    try:
        root = psutil.Process(job["pid"])
        procs = root.children(recursive=True) + [root]
    except (psutil.NoSuchProcess, KeyError):
        procs = []
    for proc in procs:
        try:
            proc.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(procs, timeout=5)
    for proc in alive:
        try:
            proc.kill()
        except psutil.NoSuchProcess:
            pass
    print(f"killed job {job['id']} ({job['name']})")
    return 0


# ---------------------------------------------------------------------------- system snapshot


def gpu_stats() -> list[dict]:
    """NVIDIA GPUs via nvidia-smi (present on any machine with the driver). Empty when there are none."""
    smi = shutil.which("nvidia-smi")
    if not smi:
        return []
    query = "name,utilization.gpu,memory.used,memory.total,temperature.gpu"
    try:
        proc = subprocess.run(
            [smi, f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, creationflags=NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    gpus = []
    for line in proc.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 5:
            continue

        def number(text: str) -> float | None:
            try:
                return float(text)
            except ValueError:
                return None

        gpus.append({
            "name": parts[0], "util": number(parts[1]), "mem_used_mb": number(parts[2]),
            "mem_total_mb": number(parts[3]), "temp_c": number(parts[4]),
        })
    return gpus


def top_processes(interval: float, count: int = 5) -> list[dict]:
    procs = list(psutil.process_iter(["name", "memory_info"]))
    for proc in procs:
        try:
            proc.cpu_percent(None)  # prime the per-process counters
        except psutil.Error:
            pass
    time.sleep(interval)
    rows = []
    for proc in procs:
        try:
            rows.append({
                "pid": proc.pid, "name": proc.info["name"] or "?", "cpu": proc.cpu_percent(None),
                "mem_mb": round((proc.info["memory_info"].rss if proc.info["memory_info"] else 0) / 1e6),
            })
        except psutil.Error:
            continue
    return sorted(rows, key=lambda r: r["cpu"], reverse=True)[:count]


def snapshot() -> dict:
    from arachne import desktop  # local import: desktop imports this module's helpers

    psutil.cpu_percent(None)
    processes = top_processes(interval=0.4)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(str(Path.home()))
    return {
        "version": __version__,
        "hostname": socket.gethostname(),
        "user": os.environ.get("USER") or os.environ.get("USERNAME") or "",
        "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "time": time.time(),
        "boot_time": psutil.boot_time(),
        "cpu": {"percent": psutil.cpu_percent(None), "cores": psutil.cpu_count() or 0},
        "memory": {"percent": memory.percent, "used_gb": round(memory.used / 1e9, 1), "total_gb": round(memory.total / 1e9, 1)},
        "disk": {"percent": disk.percent, "used_gb": round(disk.used / 1e9), "total_gb": round(disk.total / 1e9)},
        "gpus": gpu_stats(),
        "processes": processes,
        "jobs": [
            {k: j.get(k) for k in ("id", "name", "command", "status", "started", "ended", "exit", "from", "actor")}
            for j in list_jobs(limit=8)
        ],
        "activity": recent_activity(),
        "desktop": desktop.bridge_state(),
    }


def verb_stats(payload: dict) -> int:
    print(json.dumps(snapshot()))
    return 0


# ---------------------------------------------------------------------------- SSH keys


def own_public_key(create: bool = True) -> str:
    ssh_dir = Path.home() / ".ssh"
    for name in ("id_ed25519.pub", "id_ecdsa.pub", "id_rsa.pub"):
        if (ssh_dir / name).exists():
            return (ssh_dir / name).read_text().strip()
    if not create:
        raise Error("this device has no SSH key yet; run `arachne setup` here")
    ssh_dir.mkdir(mode=0o700, exist_ok=True)
    comment = f"arachne@{socket.gethostname()}"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", comment, "-f", str(ssh_dir / "id_ed25519")], check=True
    )
    return (ssh_dir / "id_ed25519.pub").read_text().strip()


def authorize_key(key: str) -> list[str]:
    """Let the holder of `key` SSH into this device. Returns the files that were changed."""
    key = " ".join(key.split())
    if not KEY_PATTERN.match(key):
        raise Error("that does not look like an SSH public key (expected e.g. 'ssh-ed25519 AAAA... comment')")
    targets = [Path.home() / ".ssh" / "authorized_keys"]
    admin_file = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "ssh" / "administrators_authorized_keys"
    if os.name == "nt" and admin_file.parent.is_dir():
        targets.append(admin_file)  # Windows OpenSSH reads only this file for administrator accounts
    changed = []
    for path in targets:
        try:
            existing = path.read_text() if path.exists() else ""
            if key.split()[1] in existing:
                continue
            path.parent.mkdir(mode=0o700, exist_ok=True)
            with path.open("a") as f:
                f.write(("" if existing.endswith("\n") or not existing else "\n") + key + "\n")
            if os.name == "nt" and path == admin_file:
                subprocess.run(
                    ["icacls", str(path), "/inheritance:r", "/grant", "*S-1-5-32-544:F", "/grant", "*S-1-5-18:F"],
                    capture_output=True, creationflags=NO_WINDOW,
                )
            elif os.name != "nt":
                path.chmod(0o600)
            changed.append(str(path))
        except PermissionError:
            if path == admin_file:
                print("arachne: need an elevated (administrator) shell to authorize keys for admin accounts", file=sys.stderr)
            else:
                raise
    return changed


# ---------------------------------------------------------------------------- peers
#
# What each device knows about the others: the username to log in with and the SSH key
# to accept. Devices exchange this when they pair, so nobody has to configure either.


def my_entry() -> dict:
    return {"user": getpass.getuser(), "key": own_public_key()}


def merge_peers(peers: dict) -> None:
    """Remember the given devices' usernames and let their keys control this device."""
    config = load_config()
    known = config.setdefault("peers", {})
    for name, entry in peers.items():
        if entry.get("key"):
            authorize_key(entry["key"])
        known[name] = {**known.get(name, {}), **{k: v for k, v in entry.items() if v}}
    save_config(config)


def verb_peers_get(payload: dict) -> int:
    print(json.dumps({"self": my_entry(), "peers": load_config().get("peers", {})}))
    return 0


def verb_peers_merge(payload: dict) -> int:
    merge_peers(payload["peers"])
    print(json.dumps({"ok": True}))
    return 0
