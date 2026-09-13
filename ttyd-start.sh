#!/bin/sh
# ttyd-web-control launcher: ttyd + proxy + persistent tmux session.
# Portable across macOS and Linux. All settings via environment variables.
#
#   TMUX_SESSION  tmux session name (default: agy)
#   TTYD_HOST     ttyd bind interface, internal only (default: 127.0.0.1)
#   TTYD_PORT     ttyd port, internal only (default: 7682)
#   PROXY_PORT    public proxy port (default: 7681)
#   FONT_SIZE     terminal font size (default: 8)
#   TTYD_PROXY    path to ttyd-proxy.py (default: same dir as this script)
#   PYTHON        python interpreter (default: first python3 on PATH)
#   USER_SHELL    shell inside tmux (default: $SHELL or sh)

set -u

# Make sure Homebrew / local bins are visible even under launchd/systemd.
case ":$PATH:" in
  *:/usr/local/bin:*) ;;
  *) export PATH="/usr/local/bin:/opt/homebrew/bin:$HOME/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}" ;;
esac

export LANG="${LANG:-en_US.UTF-8}"
export LC_ALL="${LC_ALL:-en_US.UTF-8}"

TMUX_SESSION="${TMUX_SESSION:-agy}"
TTYD_HOST="${TTYD_HOST:-127.0.0.1}"
TTYD_PORT="${TTYD_PORT:-7682}"
PROXY_PORT="${PROXY_PORT:-7681}"
FONT_SIZE="${FONT_SIZE:-8}"
USER_SHELL="${USER_SHELL:-${SHELL:-sh}}"

BIN_DIR="$(cd "$(dirname "$0")" && pwd)"
TTYD_PROXY="${TTYD_PROXY:-$BIN_DIR/ttyd-proxy.py}"
PYTHON="${PYTHON:-$(command -v python3 || true)}"

TTYD_BIN="$(command -v ttyd || true)"
TMUX_BIN="$(command -v tmux || true)"

if [ -z "$TTYD_BIN" ]; then
  echo "error: 'ttyd' not found. Install it first: https://github.com/tsl0922/ttyd" >&2
  echo "  macOS: brew install ttyd | Ubuntu/Debian: see README" >&2
  exit 1
fi
if [ -z "$TMUX_BIN" ]; then
  echo "error: 'tmux' not found. Install it first (brew install tmux / apt install tmux)." >&2
  exit 1
fi
if [ -z "$PYTHON" ]; then
  echo "error: 'python3' not found. Install Python 3.9+ first." >&2
  exit 1
fi
if ! "$PYTHON" -c "import aiohttp" 2>/dev/null; then
  echo "error: python module 'aiohttp' missing. Run: $PYTHON -m pip install --user aiohttp" >&2
  exit 1
fi

# Clean up previous instances (same ports only, never touch other sessions)
pkill -f "ttyd.*${TTYD_PORT}" 2>/dev/null || true
pkill -f "ttyd-proxy.py" 2>/dev/null || true
sleep 1

# ttyd + tmux in auto-reattach mode (DOM renderer keeps text selectable)
# shellcheck disable=SC2086
"$TTYD_BIN" -p "$TTYD_PORT" --interface "$TTYD_HOST" -W \
  -t fontSize="$FONT_SIZE" -t rendererType=dom \
  "$TMUX_BIN" new-session -A -s "$TMUX_SESSION" $USER_SHELL &
sleep 2

# Proxy runs in the foreground so supervisors (launchd/systemd) can watch it.
# Pass through the same env so ports/session stay in sync.
export TTYD_HOST TTYD_PORT PROXY_PORT TMUX_SESSION
exec "$PYTHON" "$TTYD_PROXY"
