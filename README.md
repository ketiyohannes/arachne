# arachne

Run terminal commands on your Tailscale devices over SSH.

```sh
arachne ls                          # devices on your tailnet
arachne run gpu-box                 # open a shell on gpu-box
arachne run gpu-box -- nvidia-smi   # run a command; exits with its exit code
arachne run gpu-box -u keti -- htop # as another user (interactive programs work)
```

Devices are matched by Tailscale name, hostname, IP, or a unique prefix (`arachne run gpu`).
Connections go to the device's Tailscale IP, so MagicDNS doesn't need to be on.

## Install

```sh
uv tool install git+https://github.com/ketiyohannes/arachne
```

(or `pipx install git+https://github.com/ketiyohannes/arachne`). No dependencies beyond Python 3.9+.

## Setup on each device you want to reach

1. Install Tailscale and sign in to the same tailnet.
2. Turn on an SSH server:
   - **macOS**: System Settings → General → Sharing → Remote Login.
   - **Linux**: `sudo apt install openssh-server` (or your distro's equivalent).
   - **Windows**: Settings → System → Optional features → add *OpenSSH Server*, then
     `Start-Service sshd; Set-Service sshd -StartupType Automatic` in an admin PowerShell.
3. From the machine you run `arachne` on, copy your key once so you are not asked for passwords:
   `ssh-copy-id you@<tailscale-ip>` (find the IP with `arachne ls`).

Anything in `~/.ssh/config` that applies to the IP (keys, user, options) is used as usual.

## Development

```sh
uv run --with pytest pytest
```
