#!/bin/sh
# arachne installer for macOS and Linux.
#   curl -fsSL https://raw.githubusercontent.com/ketiyohannes/arachne/main/install.sh | sh -s -- [--join URL]
# Installs Tailscale and uv if missing, then arachne, then runs `arachne setup` with the given arguments.
set -eu

REPO="git+https://github.com/ketiyohannes/arachne"
export PATH="$HOME/.local/bin:$PATH"

say() { printf '\n==> %s\n' "$1"; }

if ! command -v tailscale >/dev/null 2>&1 && [ ! -x /Applications/Tailscale.app/Contents/MacOS/Tailscale ]; then
  say "Installing Tailscale"
  if [ "$(uname)" = "Darwin" ]; then
    if command -v brew >/dev/null 2>&1; then
      brew install --cask tailscale-app
      open -a Tailscale || true
    else
      echo "Install Tailscale from https://tailscale.com/download, sign in, then run this installer again."
      exit 1
    fi
  else
    curl -fsSL https://tailscale.com/install.sh | sh
  fi
fi

if ! command -v uv >/dev/null 2>&1; then
  say "Installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi

say "Installing arachne"
uv tool install --force "$REPO"

say "Setting up this device"
# Re-attach the terminal: this script usually arrives on a pipe, and setup may need to prompt (sudo, sign-in).
if [ -e /dev/tty ]; then
  arachne setup "$@" </dev/tty
else
  arachne setup "$@"
fi
