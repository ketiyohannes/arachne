# arachne

One CLI for all your devices. Run commands and long jobs on any of them, copy files
between them, operate their desktops, and watch everything on a dashboard — from
whichever device you (or your agent) happen to be on.

```sh
arachne devices                                   # what is on my network
arachne stats                                     # CPU / memory / GPU / jobs per device
arachne run desktop -- nvidia-smi                 # run a command, exit code passes through
arachne run desktop -d -n train -C ~/proj -- 'uv run train.py'   # long job, survives disconnects
arachne logs desktop train -f                     # follow it
arachne cp -r desktop:proj/out ./out              # files, any direction, device to device too
arachne desktop desktop snapshot --app Notepad -i # see and operate a desktop
arachne dashboard --open                          # live view of everything
```

## What it is made of

arachne is glue. The heavy lifting is done by tools that already exist:

| Need | Provided by |
|---|---|
| Private network between devices, identity, NAT traversal | [Tailscale](https://tailscale.com) |
| Remote execution and file transfer | OpenSSH (`ssh`, `scp`) over the tailnet |
| Desktop control (computer use) on macOS, Windows, Linux | [agent-desktop](https://github.com/vercel-labs/agent-desktop) by Vercel Labs |
| System metrics | [psutil](https://github.com/giampaolo/psutil), `nvidia-smi` |
| Install and updates | [uv](https://docs.astral.sh/uv/) |

What arachne adds: device lookup by name, one quoting-proof way to run a command on any
OS, detached jobs with logs, a desktop bridge so GUI control works over SSH, the dashboard,
and a skill that teaches an agent to use all of it.

## Connect your devices

**1. First device** (for example your Mac):

```sh
curl -fsSL https://raw.githubusercontent.com/ketiyohannes/arachne/main/install.sh | sh
```

Windows, in an administrator PowerShell:
`& ([scriptblock]::Create((irm https://raw.githubusercontent.com/ketiyohannes/arachne/main/install.ps1)))`

It installs Tailscale, uv and arachne, asks you to sign in to Tailscale, turns on the SSH
server and starts the desktop bridge.

**2. Every other device:** on a device that is already set up, run

```sh
arachne invite
```

and paste the line it prints on the new device. Sign in to Tailscale with the same account
when asked. That is all: the two devices exchange usernames and SSH keys by themselves, the
new device is introduced to all the others, and `arachne invite` confirms with
`ok  desktop joined`. One invite stays open for 30 minutes and accepts any number of devices.

**3. Check:** `arachne doctor` verifies this device and the connection to each other one,
and prints the fix for anything that is wrong.

There is nothing else to configure: no config file, no key copying, no usernames to enter.
Every paired device can control every other one, so your agent can run from any of them.

Good to know:

- **macOS desktop control** needs a one-time grant: run `arachne desktop <mac> permissions --guide`
  at that Mac (Accessibility; Screen Recording for screenshots).
- `arachne setup` is safe to re-run on any device; it only fixes what is missing.
- If a device was offline while another one joined, `arachne sync` brings it up to date.
- Only devices signed in to *your* Tailscale account can answer an invite; devices shared
  into your tailnet by someone else are refused.

## Commands

| Command | What it does |
|---|---|
| `arachne devices [-a] [--json]` | Devices on the tailnet (`-a` includes offline) |
| `arachne run HOST [-C DIR] [-e K=V] -- CMD` | Run in the device's shell (login shell on macOS/Linux, PowerShell on Windows) |
| `arachne run HOST -d [-n NAME] -- CMD` | Start a detached job |
| `arachne jobs [HOST]`, `logs HOST JOB [-f] [-t N]`, `kill HOST JOB` | Manage jobs |
| `arachne run HOST --raw -- CMD` | Plain ssh, for devices without arachne |
| `arachne ssh HOST` | Interactive shell |
| `arachne cp [-r] SRC... DST` | Copy files; either side may be `DEVICE:PATH` (relative to home) |
| `arachne desktop HOST ARGS...` | Run `agent-desktop ARGS` on the device's screen; `-o FILE screenshot` saves the image here |
| `arachne stats [HOST] [--json]` | Load, GPU, jobs |
| `arachne dashboard [--port N] [--tailnet] [--open]` | Web dashboard: resources, what is running, trace |
| `arachne invite` | Add devices: prints one line to paste on them, then pairs automatically |
| `arachne doctor` | Check this device and every connection, with fixes |
| `arachne setup`, `sync`, `user DEVICE NAME` | Repair this device, re-share pairing info, override a username |
| `arachne skill [install]` | Print the agent skill, or install it into `~/.claude/skills/arachne` |

Devices match by Tailscale name, hostname, IP or unique prefix; `self` is this machine.

## For agents

`arachne setup` installs a Claude Code skill automatically when `~/.claude` exists. For any
other agent, `arachne skill` prints the same instructions; put them wherever that agent reads
its guidance. The skill covers picking a device by capability, jobs, file transfer and the
desktop loop.

## Dashboard

`arachne dashboard` serves a read-only page on `http://127.0.0.1:7777` with three tabs:

- **Resources**: one card per device with CPU, memory, disk, GPU and VRAM, the last ten
  minutes of load, and its latest command. Open "Details" for its top processes.
- **Running now**: every command and job in progress, with a live tail of its output.
- **Trace**: everything that was run through arachne (commands, jobs, desktop actions),
  newest first, with who ran it (for example `claude-code`), where from, the result and how
  long it took. Click an entry to read its output. Filter by device or by who ran it.

Output is recorded on the device that ran the command (`~/.arachne/runs/`, last 300
commands, 256 KB each); commands typed in an interactive terminal are listed but their
output is not recorded. Set `ARACHNE_ACTOR=name` to label what an agent or script runs.

There is no login. With `--tailnet` it listens on this device's Tailscale address instead,
so your other devices (and nothing else) can open it.

### Open it from anywhere

To see the dashboard away from your tailnet, host the page and keep the data behind a key:

1. **Hub**: on an always-on device of yours, run `arachne dashboard --bind 0.0.0.0` (as a
   service) and give it an HTTPS address that requires a token, such as a private published
   port on your VPS provider or a reverse proxy.
2. **Page**: deploy `dashboard/` to Vercel (`vercel deploy --prod`) with three environment
   variables: `HUB_URL` (the hub's address), `HUB_TOKEN` (the bearer token that address
   requires, if any) and `DASHBOARD_KEY` (any long random string).
3. Open `https://<your-deployment>/#key=<DASHBOARD_KEY>` once per browser. The key is kept
   in that browser; without it the deployment returns nothing.

The hub address and its token stay on the server side of the deployment.

## How it works

- Every device runs the same package. The controller sends `arachne _ VERB <base64 json>`
  over SSH, so commands never get mangled by sh, cmd.exe or PowerShell quoting.
- Jobs are plain processes under a small supervisor, with state in `~/.arachne/jobs/<id>/`.
- An SSH session cannot reach the screen (Windows session 0, no display on Linux, per-app
  permissions on macOS). So `arachne setup` registers a login item, the **desktop bridge**,
  which runs inside your desktop session, listens on 127.0.0.1 only, requires a token only
  your user can read, and can run nothing but `agent-desktop`.
- Host keys of new devices are accepted on first contact (the tailnet already authenticates
  the peer); a changed key is still refused.

## Security

Paired devices trust each other fully: each accepts the others' SSH keys. Anyone holding
an authorized key controls the device, exactly as with plain SSH.
Access is limited to your tailnet. The dashboard is unauthenticated by design: keep it on
127.0.0.1, or on the tailnet if everyone on your tailnet may see it.

## Development

```sh
uv run pytest
```

The dashboard page is a React + TypeScript + Tailwind app in `dashboard/`. It builds to a
single self-contained file that is committed at `src/arachne/dashboard.html`, so installing
arachne never needs Node:

```sh
cd dashboard && bun install && bun run build   # rebuilds src/arachne/dashboard.html
bun run dev                                    # hot reload, proxies /api to a running `arachne dashboard`
```

Append `?demo` to the dashboard URL to preview it with a made-up fleet.

Tests use a fake tailnet (`ARACHNE_TAILSCALE_STATUS`) and run every command against the
local device, so they need neither Tailscale nor SSH.
