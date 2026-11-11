import json

import pytest

STATUS = {
    "BackendState": "Running",
    "MagicDNSSuffix": "tail0000.ts.net",
    "Self": {"HostName": "Mac Book", "DNSName": "macbook.tail0000.ts.net.", "OS": "macOS", "TailscaleIPs": ["100.64.0.1"]},
    "Peer": {
        "a": {"HostName": "DESKTOP-4070", "DNSName": "desktop.tail0000.ts.net.", "OS": "windows",
              "TailscaleIPs": ["100.64.0.2"], "Online": True, "CurAddr": "192.168.1.9:41641", "Relay": "fra"},
        "b": {"HostName": "devbox", "DNSName": "devbox.tail0000.ts.net.", "OS": "linux",
              "TailscaleIPs": ["100.64.0.3"], "Online": True, "CurAddr": "", "Relay": "lhr"},
        "c": {"HostName": "old-laptop", "DNSName": "deck.tail0000.ts.net.", "OS": "linux",
              "TailscaleIPs": ["100.64.0.4"], "Online": False, "CurAddr": "", "Relay": "lhr"},
    },
}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Every test gets its own home, arachne state directory and fake tailnet."""
    status = tmp_path / "status.json"
    status.write_text(json.dumps(STATUS))
    monkeypatch.setenv("ARACHNE_TAILSCALE_STATUS", str(status))
    monkeypatch.setenv("ARACHNE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("SHELL", "/bin/sh")
    monkeypatch.delenv("SSH_CONNECTION", raising=False)
    return tmp_path
