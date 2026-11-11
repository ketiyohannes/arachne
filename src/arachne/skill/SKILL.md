---
name: arachne
description: Use the user's other computers (GPU desktop, laptops, servers) from here with the `arachne` CLI - run commands and long jobs on them, copy files between them, check their CPU/GPU load, and see or operate their desktops. Use when a task should run on another machine (training or fine-tuning on a GPU box, builds or CI on another OS, testing on Windows/Linux/macOS), when the user names one of their devices, or asks what their machines are doing.
---

# arachne: use the user's other devices

`arachne` reaches every device on the user's Tailscale network over SSH. Devices are
addressed by name (unique prefixes work, `self` is this machine).

## 1. Find the right device

```sh
arachne devices            # names, OS, online state
arachne stats              # CPU, memory, disk, GPU (name, load, VRAM), running jobs per device
arachne stats --json       # the same, machine-readable
```

Pick by capability: for GPU work choose the device whose `stats` shows a GPU with free VRAM.

## 2. Run commands

```sh
arachne run desktop -- nvidia-smi
arachne run desktop -C ~/proj -e HF_HOME=/data/hf -- 'uv sync && pytest -q'
```

- Exit code, stdout and stderr pass through. `-C` sets the directory, `-e KEY=VALUE` adds environment.
- The text after `--` runs in the device's shell: the user's login shell on macOS/Linux,
  **PowerShell on Windows**. Check the OS in `arachne devices` and write the command for it.
- Quote the whole command as one argument when it contains `&&`, pipes, `$VARS` or globs,
  so they are evaluated on the device and not here.

## 3. Long-running work: detached jobs

Anything that takes more than a minute or two (training, big builds, downloads) must be a job.
Jobs survive disconnects and keep a log on the device.

```sh
arachne run desktop -d -n finetune -C ~/proj -- 'python train.py --epochs 3'
arachne jobs                      # all devices; or: arachne jobs desktop
arachne logs desktop finetune -t 40      # last 40 lines
arachne logs desktop finetune -f         # stream until it ends; exits with the job's exit code
arachne kill desktop finetune
```

Statuses: `running`, `done` (exit 0), `failed`, `killed`, `lost` (device rebooted mid-job).
Check on a job with `-t` periodically rather than holding `-f` open for hours.

## 4. Move files

```sh
arachne cp ./data.jsonl desktop:proj/data/           # here -> device (paths are relative to its home)
arachne cp -r desktop:proj/checkpoints ./out/        # device -> here
arachne cp desktop:model.gguf laptop:models/         # device -> device
```

For code, prefer `git clone`/`git pull` on the device; use `cp` for data, artifacts and scripts.

## 5. Typical flow: "run this on the 4070 instead of here"

1. `arachne stats` - confirm the GPU device is online and has free VRAM.
2. Get the code there: `arachne run desktop -- 'git clone URL proj'` or `arachne cp -r . desktop:proj`.
3. Prepare: `arachne run desktop -C ~/proj -- 'uv sync'`.
4. Start: `arachne run desktop -d -n train -C ~/proj -- 'uv run train.py'`.
5. Watch: `arachne logs desktop train -t 30`; when `arachne jobs desktop` shows `done`,
   fetch results with `arachne cp -r desktop:proj/out ./out`.

## 6. Operate a device's desktop (computer use)

`arachne desktop HOST ...` runs [agent-desktop](https://github.com/vercel-labs/agent-desktop) on that
device's screen. It works from the accessibility tree: take a snapshot, act on an element ref,
snapshot again to verify.

```sh
arachne desktop desktop skills get desktop        # READ THIS FIRST: the loop, refs, retry rules
arachne desktop desktop skills get platform       # what differs on that device's OS
arachne desktop desktop status                    # permissions and readiness
arachne desktop desktop list-apps
arachne desktop desktop snapshot --app Notepad -i # interactive elements with refs like @s8f3k2p9:e8
arachne desktop desktop click @s8f3k2p9:e8
echo 'hello' | arachne desktop desktop type @s8f3k2p9:e4 --stdin
arachne desktop desktop -o shot.png screenshot    # saves the PNG on THIS machine; then read it
```

- Every call prints one JSON envelope (`ok`, `data` or `error`). Refs are only valid for the
  snapshot they came from; on `STALE_REF` take a new snapshot.
- Prefer `arachne run` whenever a shell command can do the job; use the desktop only for GUI-only tasks.
- If it reports that the desktop bridge is not running, someone must be signed in to that device's
  desktop and have run `arachne setup` there. On macOS, `PERM_DENIED` means the user has to grant
  Accessibility / Screen Recording once: ask them to run `arachne desktop HOST permissions --guide` at that Mac.

## 7. When something fails

- `exit 255` / "could not open an SSH session": run `arachne doctor`. It checks this device and the
  connection to every other one and prints the fix. A device that was never paired needs the user to
  run `arachne invite` here and paste the printed line on that device.
- "arachne is not installed on HOST": use `arachne run --raw HOST -- cmd` (plain ssh; no `-d`, `-C`, `-e`)
  or ask the user to add the device with `arachne invite`.
- The user can watch everything you run, with its output, in `arachne dashboard` (Trace tab).

Be careful with destructive commands on remote devices: they are the user's real machines.
Confirm before deleting data, rebooting, or installing system-wide software.
