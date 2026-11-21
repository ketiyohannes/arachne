import base64
import json
import stat
import threading
import time
import urllib.error
import urllib.request

import pytest

from arachne import agent, cli, core, dashboard, desktop, pairing, provision, remote
from tests.conftest import STATUS


def devs():
    return core.devices(core.tailscale_status())


# ---------------------------------------------------------------------------- tailnet


def test_devices_lists_self_first_with_link_kinds():
    found = devs()
    assert [d["name"] for d in found] == ["macbook", "desktop", "devbox", "deck"]
    assert [d["link"] for d in found] == ["self", "direct", "relay", "offline"]
    assert found[1]["os"] == "windows"


def test_find_device_by_name_prefix_hostname_ip_and_self():
    found = devs()
    assert core.find_device(found, "desktop")["ip"] == "100.64.0.2"
    assert core.find_device(found, "DESKTOP-4070")["name"] == "desktop"
    assert core.find_device(found, "100.64.0.3")["name"] == "devbox"
    assert core.find_device(found, "mac")["self"]
    assert core.find_device(found, "self")["self"]
    with pytest.raises(core.Error, match="ambiguous"):
        core.find_device(found, "de")
    with pytest.raises(core.Error, match="no device"):
        core.find_device(found, "nope")


def test_resolve_rejects_offline_and_stopped_tailscale(isolated):
    with pytest.raises(core.Error, match="offline"):
        core.resolve("deck")
    (isolated / "status.json").write_text(json.dumps({**STATUS, "BackendState": "Stopped"}))
    with pytest.raises(core.Error, match="not connected"):
        core.resolve("desktop")


# ---------------------------------------------------------------------------- transport


def test_remote_invocation_is_shell_safe_per_os():
    found = devs()
    payload = {"command": "echo \"it's\" && dir | findstr $x"}
    unix = remote.remote_invocation(core.find_device(found, "devbox"), "exec", payload)
    windows = remote.remote_invocation(core.find_device(found, "desktop"), "exec", payload)
    assert unix.startswith('"$HOME/.local/bin/arachne" _ exec ')
    assert windows.startswith('cmd /c "%USERPROFILE%\\.local\\bin\\arachne.exe" _ exec ')
    for line in (unix, windows):
        blob = line.rsplit(" ", 1)[1]
        assert all(c.isalnum() or c in "-_=" for c in blob)
        assert remote.decode(blob) == payload


def test_windows_payload_limit():
    with pytest.raises(core.Error, match="too long"):
        remote.remote_invocation(core.find_device(devs(), "desktop"), "exec", {"command": "x" * 9000})


def test_ssh_argv_uses_tailscale_ip_and_configured_user():
    dev = core.find_device(devs(), "devbox")
    assert remote.ssh_argv(dev, "true")[-2:] == ["100.64.0.3", "true"]
    assert cli.main(["user", "devbox", "keti"]) == 0
    argv = remote.ssh_argv(dev, "true")
    assert argv[-2] == "keti@100.64.0.3"
    assert "BatchMode=yes" in argv
    assert remote.ssh_argv(dev, "true", user="root")[-2] == "root@100.64.0.3"


def test_command_line_quotes_for_target_shell():
    found = devs()
    linux, windows = core.find_device(found, "devbox"), core.find_device(found, "desktop")
    assert cli.command_line(linux, ["echo hi && ls"]) == "echo hi && ls"
    assert cli.command_line(linux, ["echo", "a b"]) == "echo 'a b'"
    assert cli.command_line(windows, ["echo", "a b"]) == 'echo "a b"'


def test_split_endpoint():
    found = devs()
    assert cli.split_endpoint("./file.txt", found) == (None, "./file.txt")
    assert cli.split_endpoint("C:\\data\\x", found) == (None, "C:\\data\\x")
    dev, path = cli.split_endpoint("desktop:proj/data", found)
    assert (dev["name"], path) == ("desktop", "proj/data")
    assert cli.split_endpoint("devbox:", found)[1] == ""
    assert cli.split_endpoint("self:notes.txt", found) == (None, "notes.txt")
    with pytest.raises(core.Error, match="offline"):
        cli.split_endpoint("deck:x", found)


# ---------------------------------------------------------------------------- running on this device (no ssh)


def test_run_passes_exit_code_cwd_env_and_logs_activity(isolated, capfd):
    work = isolated / "work"
    work.mkdir()
    code = cli.main(["run", "self", "-C", str(work), "-e", "GREETING=hello", "--", "echo $GREETING from $(pwd); exit 7"])
    assert code == 7
    out = capfd.readouterr().out
    assert out.startswith("hello from ") and out.strip().endswith("/work")
    entry = agent.recent_activity()[0]
    assert entry["exit"] == 7 and entry["from"] == "local" and "GREETING" in entry["command"]


def test_run_reports_missing_directory(capfd):
    assert cli.main(["run", "self", "-C", "/no/such/dir", "--", "true"]) == 1
    assert "no such directory" in capfd.readouterr().err


def wait_for_status(name, wanted, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = next(j for j in agent.list_jobs() if j["name"] == name)
        if job["status"] in wanted:
            return job
        time.sleep(0.1)
    raise AssertionError(f"job {name} stayed {job['status']}")


def test_detached_job_lifecycle(capfd):
    assert cli.main(["run", "self", "-d", "-n", "build", "--", "echo line1; echo line2; exit 3"]) == 0
    assert "started job" in capfd.readouterr().out
    job = wait_for_status("build", {"failed"})
    assert job["exit"] == 3
    assert cli.main(["logs", "self", "build", "-t", "1"]) == 0
    assert capfd.readouterr().out == "line2\n"
    assert cli.main(["logs", "self", "build", "-f"]) == 3  # follow exits with the job's code
    assert cli.main(["jobs", "self"]) == 0
    assert "failed" in capfd.readouterr().out


def test_kill_stops_a_running_job_and_its_children(capfd):
    assert cli.main(["run", "self", "-d", "-n", "sleeper", "--", "sleep 300 & sleep 300; wait"]) == 0
    job = wait_for_status("sleeper", {"running"})
    while "pid" not in job:
        time.sleep(0.05)
        job = wait_for_status("sleeper", {"running"})
    assert cli.main(["kill", "self", "sleeper"]) == 0
    assert wait_for_status("sleeper", {"killed"})["status"] == "killed"


def test_stats_snapshot_shape(capfd):
    assert cli.main(["stats", "self", "--json"]) == 0
    stats = json.loads(capfd.readouterr().out)["macbook"]
    assert 0 <= stats["cpu"]["percent"] <= 100 * stats["cpu"]["cores"]
    assert stats["memory"]["total_gb"] > 0 and isinstance(stats["gpus"], list)
    assert stats["desktop"]["running"] is False


# ---------------------------------------------------------------------------- desktop bridge


@pytest.fixture
def bridge(isolated):
    fake = isolated / "agent-desktop"
    fake.write_text('#!/bin/sh\nif [ "$1" = fail ]; then echo boom >&2; exit 1; fi\nprintf \'{"ok":true,"args":"%s","stdin":"%s"}\' "$*" "$(cat)"\n')
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    core.save_config({"agent_desktop": str(fake)})
    threading.Thread(target=desktop.serve_bridge, args=(0,), daemon=True).start()
    for _ in range(100):
        if desktop.bridge_file().exists():
            return
        time.sleep(0.02)
    raise AssertionError("bridge did not start")


def test_desktop_round_trip_through_bridge(bridge, capfd, monkeypatch):
    assert cli.main(["desktop", "self", "snapshot", "--app", "Finder", "-i"]) == 0
    assert json.loads(capfd.readouterr().out) == {"ok": True, "args": "snapshot --app Finder -i", "stdin": ""}
    assert cli.main(["desktop", "self", "fail"]) == 1
    assert "boom" in capfd.readouterr().err


def test_bridge_rejects_wrong_token(bridge):
    info = json.loads(desktop.bridge_file().read_text())
    assert stat.S_IMODE(desktop.bridge_file().stat().st_mode) == 0o600
    info["token"] = "wrong"
    desktop.bridge_file().write_text(json.dumps(info))
    with pytest.raises(core.Error, match="did not answer"):
        desktop.ask_bridge(["status"])


def test_desktop_without_bridge_explains(capfd):
    assert cli.main(["desktop", "self", "status"]) == 1
    assert "bridge is not running" in capfd.readouterr().err


def test_screenshot_is_saved_locally(isolated, capfd):
    png = desktop.PNG_MAGIC + b"pixels" * 20
    envelope = {"ok": True, "command": "screenshot", "data": {"image": base64.b64encode(png).decode(), "width": 2}}
    out = isolated / "shot.png"
    assert desktop.print_result({"code": 0, "stdout": json.dumps(envelope), "stderr": ""}, str(out)) == 0
    assert out.read_bytes() == png
    printed = json.loads(capfd.readouterr().out)
    assert printed["data"]["path"] == str(out) and printed["data"]["image"] == "<saved to file>"


# ---------------------------------------------------------------------------- keys, skill, dashboard

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFakeKeyMaterialForTestsOnly000000000000000000 keti@mac"


def test_authorize_key_is_idempotent_and_validated(isolated):
    assert agent.authorize_key(KEY) == [str(isolated / ".ssh" / "authorized_keys")]
    assert agent.authorize_key(KEY) == []
    path = isolated / ".ssh" / "authorized_keys"
    assert path.read_text() == KEY + "\n" and stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(core.Error, match="SSH public key"):
        agent.authorize_key("rm -rf / # not a key")


OTHER_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOtherDeviceKeyForTestsOnly0000000000000000000 keti@desktop"


def test_pairing_exchanges_users_and_keys_and_tells_the_others(isolated, monkeypatch):
    (isolated / ".ssh").mkdir()
    (isolated / ".ssh" / "id_ed25519.pub").write_text(KEY + "\n")
    core.save_config({"peers": {"devbox": {"user": "dev", "key": OTHER_KEY.replace("Other", "Third")}}})
    desktop_dev = core.find_device(devs(), "desktop")
    joined = []
    server = pairing.invite_server("127.0.0.1", "tok", lambda dev, entry: joined.append((dev["name"], entry)), identify=lambda ip: desktop_dev)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"

    def post(path, body):
        request = urllib.request.Request(url + path, data=json.dumps(body).encode())
        return json.loads(urllib.request.urlopen(request, timeout=5).read())

    answer = post("/tok", {"user": "keti", "key": OTHER_KEY})
    assert answer["name"] == "desktop" and answer["inviter"] == "macbook"
    assert set(answer["peers"]) == {"devbox", "desktop", "macbook"} and answer["peers"]["macbook"]["key"] == KEY
    assert joined == [("desktop", {"user": "keti", "key": OTHER_KEY})]
    # The inviter now logs in to the newcomer with the right username, and accepts its key.
    assert remote.ssh_argv(desktop_dev, "true")[-2] == "keti@100.64.0.2"
    assert OTHER_KEY in (isolated / ".ssh" / "authorized_keys").read_text()
    with pytest.raises(urllib.error.HTTPError, match="403"):
        post("/wrong", {"user": "x", "key": OTHER_KEY})
    server.shutdown()


def test_pairing_refuses_devices_of_another_owner(isolated):
    server = pairing.invite_server("127.0.0.1", "tok", lambda *a: None, identify=lambda ip: None)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    request = urllib.request.Request(f"http://127.0.0.1:{server.server_address[1]}/tok", data=b"{}")
    with pytest.raises(urllib.error.HTTPError, match="403"):
        urllib.request.urlopen(request, timeout=5)
    assert not (isolated / ".ssh" / "authorized_keys").exists()
    server.shutdown()


def test_join_explains_an_expired_invite():
    with pytest.raises(core.Error, match="could not reach the inviting device"):
        pairing.join("http://127.0.0.1:9/expired")


def test_same_owner_check_uses_tailscale_identity(isolated):
    status = json.loads((isolated / "status.json").read_text())
    status["Self"]["UserID"] = 1
    status["Peer"]["a"]["UserID"] = 1
    status["Peer"]["b"]["UserID"] = 2  # shared in from someone else
    (isolated / "status.json").write_text(json.dumps(status))
    assert pairing.own_device_at("100.64.0.2")["name"] == "desktop"
    assert pairing.own_device_at("100.64.0.3") is None
    assert pairing.own_device_at("100.64.0.1") is None and pairing.own_device_at("10.0.0.1") is None


def test_skill_install(isolated):
    target = provision.install_skill(str(isolated / "skills" / "arachne"))
    text = (target / "SKILL.md").read_text()
    assert text.startswith("---\nname: arachne\n") and "arachne run" in text


def test_dashboard_state_names_callers_and_marks_unreachable(monkeypatch):
    def fake_call(dev, verb, payload=None, user=None, timeout=30):
        if dev["name"] == "devbox":
            raise core.Error("devbox: could not open an SSH session")
        return {"jobs": [{"from": "100.64.0.1"}], "activity": [{"from": "local"}, {"from": "100.64.0.9"}]}

    monkeypatch.setattr(remote, "call_json", fake_call)
    state = dashboard.collect()
    by_name = {d["name"]: d for d in state["devices"]}
    assert state["tailnet"] == "tail0000.ts.net" and state["tailscale"] == "Running"
    assert by_name["desktop"]["stats"]["jobs"][0]["from"] == "macbook"
    assert [e["from"] for e in by_name["desktop"]["stats"]["activity"]] == ["desktop", "100.64.0.9"]
    assert "SSH session" in by_name["devbox"]["error"]
    assert "stats" not in by_name["deck"] and "error" not in by_name["deck"]



def test_command_output_and_actor_are_recorded_for_the_trace(capfd, monkeypatch):
    monkeypatch.setenv("ARACHNE_ACTOR", "claude-code")
    assert cli.main(["run", "self", "--", "echo to-out; echo to-err >&2; exit 4"]) == 4
    captured = capfd.readouterr()
    assert captured.out == "to-out\n" and captured.err.startswith("to-err\n")  # streams still reach the caller
    entry = agent.recent_activity()[0]
    assert entry["actor"] == "claude-code" and entry["kind"] == "run" and entry["exit"] == 4
    assert agent.verb_output({"id": entry["id"]}) == 0
    recorded = json.loads(capfd.readouterr().out)
    assert "to-out" in recorded["text"] and "to-err" in recorded["text"]
    assert agent.verb_output({"id": "ffffffff"}) == 0
    assert json.loads(capfd.readouterr().out)["missing"] is True
    with pytest.raises(core.Error):
        agent.verb_output({"id": "../../etc/passwd"})


def test_job_output_and_desktop_actions_appear_in_the_trace(bridge, capfd):
    assert cli.main(["run", "self", "-d", "-n", "noisy", "--", "echo from-job"]) == 0
    wait_for_status("noisy", {"done"})
    capfd.readouterr()
    assert agent.verb_output({"id": "noisy", "kind": "job"}) == 0
    assert json.loads(capfd.readouterr().out)["text"] == "from-job\n"
    assert cli.main(["desktop", "self", "list-apps"]) == 0
    entry = next(e for e in agent.recent_activity() if e["kind"] == "desktop")
    assert entry["command"] == "agent-desktop list-apps" and entry["exit"] == 0


def test_dashboard_output_endpoint_reads_from_the_device(capfd):
    assert cli.main(["run", "self", "--", "echo visible-in-dashboard"]) == 0
    entry = agent.recent_activity()[0]
    result = dashboard.fetch_output({"device": ["macbook"], "id": [entry["id"]]})
    assert "visible-in-dashboard" in result["text"]
    assert "error" in dashboard.fetch_output({"device": ["nope"], "id": ["x"]})
    assert "error" in dashboard.fetch_output({})


def test_dashboard_history_keeps_recent_load_per_device():
    history: dict = {}
    stats = {"cpu": {"percent": 12.5}, "memory": {"percent": 40.0}, "gpus": [{"util": 77}]}
    for generated in (100.0, 105.0):
        state = {"generated": generated, "devices": [{"name": "desktop", "stats": stats}, {"name": "deck"}]}
        dashboard.record_history(history, state)
    assert state["devices"][0]["history"] == [[100, 12.5, 40.0, 77], [105, 12.5, 40.0, 77]]
    assert state["devices"][1]["history"] == []
