#!/usr/bin/env bash
# One-shot installer for Linux.
#
#   ./install.sh            install system packages + Python venv
#   ./install.sh --uinput   additionally grant this user access to /dev/uinput
#                           (lets the bot type into BDO under Proton/Wine as a
#                           virtual keyboard; needs sudo, then log out/in once)
#   ./install.sh --no-system  skip the distro package step (venv only)
#
# Afterwards:   ./run.sh --dry-run        ./run.sh calibrate preview
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

WANT_UINPUT=0
SKIP_SYSTEM=0
for arg in "$@"; do
  case "$arg" in
    --uinput) WANT_UINPUT=1 ;;
    --no-system) SKIP_SYSTEM=1 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  if command -v sudo >/dev/null 2>&1; then SUDO="sudo"; else SUDO=""; fi
fi

# ----------------------------------------------------------------- system deps
# python3-tk: pyautogui imports tkinter.  python3-dev + compiler + kernel
# headers: evdev has no binary wheels and builds against linux/input.h.
install_system_packages() {
  if command -v apt-get >/dev/null 2>&1; then
    info "Installing system packages with apt"
    $SUDO apt-get update -qq
    $SUDO apt-get install -y -qq python3 python3-venv python3-pip python3-dev python3-tk build-essential
  elif command -v dnf >/dev/null 2>&1; then
    info "Installing system packages with dnf"
    $SUDO dnf install -y python3 python3-pip python3-devel python3-tkinter gcc kernel-headers
  elif command -v pacman >/dev/null 2>&1; then
    info "Installing system packages with pacman"
    $SUDO pacman -Sy --needed --noconfirm python python-pip tk base-devel linux-api-headers
  elif command -v zypper >/dev/null 2>&1; then
    info "Installing system packages with zypper"
    $SUDO zypper --non-interactive install python3 python3-pip python3-devel python3-tk gcc linux-glibc-devel
  else
    warn "Unknown package manager. Install python3 (>=3.10) with venv/pip, the Python headers,"
    warn "tkinter, a C compiler and kernel headers yourself, then re-run with --no-system."
    return 1
  fi
}

if [ "$SKIP_SYSTEM" -eq 0 ]; then
  if [ -z "$SUDO" ] && [ "$(id -u)" -ne 0 ]; then
    warn "sudo not found; skipping system packages"
  else
    install_system_packages || true
  fi
fi

# ----------------------------------------------------------------- python venv
PY=python3
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "python3 not found" >&2; exit 1
fi
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "Python 3.10 or newer is required (found $("$PY" --version))" >&2; exit 1
fi

if [ ! -d .venv ]; then
  info "Creating virtual environment in .venv"
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
info "Installing Python dependencies"
pip install --quiet --upgrade pip wheel
pip install --quiet -e .

info "Checking imports"
python - <<'EOF'
import importlib, sys
missing = []
for mod in ("cv2", "numpy", "mss", "pynput", "pyautogui", "evdev"):
    try:
        importlib.import_module(mod)
    except Exception as exc:  # noqa: BLE001
        missing.append(f"{mod}: {exc}")
if missing:
    print("Some optional modules failed to import:\n  " + "\n  ".join(missing))
else:
    print("All modules import fine.")
EOF

# --------------------------------------------------------------- uinput access
if [ "$WANT_UINPUT" -eq 1 ]; then
  if [ -z "$SUDO" ] && [ "$(id -u)" -ne 0 ]; then
    warn "--uinput needs sudo/root; skipping"
  else
    info "Granting access to /dev/uinput (group 'input')"
    $SUDO groupadd -f input
    $SUDO usermod -aG input "${SUDO_USER:-$USER}"
    $SUDO mkdir -p /etc/udev/rules.d /etc/modules-load.d
    echo 'KERNEL=="uinput", SUBSYSTEM=="misc", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"' \
      | $SUDO tee /etc/udev/rules.d/99-bdo-fishing-bot-uinput.rules >/dev/null
    echo uinput | $SUDO tee /etc/modules-load.d/bdo-fishing-bot-uinput.conf >/dev/null
    $SUDO modprobe uinput 2>/dev/null || true
    if command -v udevadm >/dev/null 2>&1; then
      $SUDO udevadm control --reload-rules 2>/dev/null || true
      $SUDO udevadm trigger --name-match=uinput 2>/dev/null || true
    fi
    if [ -e /dev/uinput ]; then
      # Apply the permissions right away too, so only the group change needs a re-login.
      $SUDO chgrp input /dev/uinput 2>/dev/null || true
      $SUDO chmod 0660 /dev/uinput 2>/dev/null || true
      warn "Group membership only applies to new sessions: log out and back in before running the bot."
    else
      warn "/dev/uinput does not exist on this system (kernel without the uinput module?)."
      warn "The bot will use the pyautogui (XTEST) backend instead."
    fi
  fi
fi

# ------------------------------------------------------------------- summary
echo
info "Installed. Next steps:"
cat <<'EOF'
  1. Start Black Desert (Steam/Proton or Wine), 1920x1080, UI scale 100, windowed/borderless.
  2. ./run.sh calibrate preview            # check the detection regions
  3. ./run.sh calibrate burst --region wasd # capture key icons, see templates/README.md
  4. ./run.sh --dry-run -v                  # watch detections while fishing by hand
  5. ./run.sh                               # go
EOF

if [ "${XDG_SESSION_TYPE:-}" = "wayland" ]; then
  echo
  warn "You are on a Wayland session. Screen capture (mss) and the pause/stop hotkeys (pynput)"
  warn "only work on X11. Log in with an 'X11' / 'Xorg' session from your display manager."
fi
if [ "$WANT_UINPUT" -eq 0 ] && ! [ -w /dev/uinput ]; then
  echo
  echo "Tip: the game may ignore XTEST (pyautogui) key presses. Run './install.sh --uinput' to let"
  echo "     the bot act as a virtual keyboard instead."
fi
