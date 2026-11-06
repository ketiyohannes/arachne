import pytest

import arachne

STATUS = {
    "BackendState": "Running",
    "Self": {"HostName": "Keti's MacBook Pro", "DNSName": "ketis-macbook-pro.tail1.ts.net.",
             "OS": "macOS", "TailscaleIPs": ["100.64.0.1", "fd7a::1"]},
    "Peer": {
        "a": {"HostName": "gpu-box", "DNSName": "gpu-box.tail1.ts.net.", "OS": "linux",
              "Online": True, "TailscaleIPs": ["100.64.0.2"]},
        "b": {"HostName": "gpu-box-old", "DNSName": "gpu-box-old.tail1.ts.net.", "OS": "windows",
              "Online": False, "TailscaleIPs": ["100.64.0.3"]},
        "c": {"HostName": "KT's S22+", "DNSName": "kts-s22.tail1.ts.net.", "OS": "android",
              "Online": True, "TailscaleIPs": ["100.64.0.4"]},
    },
}


def test_devices_use_magicdns_short_names_and_put_online_first():
    devs = arachne.devices(STATUS)
    assert [(d["name"], d["online"]) for d in devs] == [
        ("gpu-box", True), ("ketis-macbook-pro", True), ("kts-s22", True), ("gpu-box-old", False),
    ]
    assert next(d for d in devs if d["self"])["ip"] == "100.64.0.1"


@pytest.mark.parametrize("query,expected", [
    ("gpu-box", "gpu-box"),            # exact name wins over the longer prefix match
    ("GPU-BOX-OLD", "gpu-box-old"),
    ("gpu-box.tail1.ts.net.", "gpu-box"),
    ("100.64.0.4", "kts-s22"),
    ("KT's S22+", "kts-s22"),          # original hostname
    ("ketis", "ketis-macbook-pro"),    # unique prefix
])
def test_find_device(query, expected):
    assert arachne.find_device(arachne.devices(STATUS), query)["name"] == expected


def test_find_device_errors_name_the_options():
    devs = arachne.devices(STATUS)
    with pytest.raises(arachne.Error, match="ambiguous: gpu-box, gpu-box-old"):
        arachne.find_device(devs, "gpu")
    with pytest.raises(arachne.Error, match="no device named 'nas'.*gpu-box"):
        arachne.find_device(devs, "nas")


def test_ssh_argv_tty_only_for_interactive_commands(monkeypatch):
    monkeypatch.setattr(arachne.shutil, "which", lambda _: "/usr/bin/ssh")
    dev = arachne.devices(STATUS)[0]
    assert arachne.ssh_argv(dev, ["top"], None, tty=True) == ["/usr/bin/ssh", "-t", "100.64.0.2", "top"]
    assert arachne.ssh_argv(dev, ["ls", "-la"], "keti", tty=False) == ["/usr/bin/ssh", "keti@100.64.0.2", "ls", "-la"]
    assert arachne.ssh_argv(dev, [], None, tty=True) == ["/usr/bin/ssh", "100.64.0.2"]


def test_stopped_tailscale_is_reported(monkeypatch):
    class Done:
        stdout = '{"BackendState": "Stopped", "Self": {}}'
        stderr = ""

    monkeypatch.setattr(arachne, "tailscale_bin", lambda: "tailscale")
    monkeypatch.setattr(arachne.subprocess, "run", lambda *a, **k: Done())
    with pytest.raises(arachne.Error, match="not connected.*Stopped"):
        arachne.tailscale_status()
