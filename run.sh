#!/usr/bin/env bash
# Run the bot (or the calibration tools) from the venv created by install.sh.
#
#   ./run.sh [bot options]                e.g. ./run.sh --dry-run -v
#   ./run.sh calibrate <subcommand> ...   e.g. ./run.sh calibrate preview
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

if [ ! -x .venv/bin/python ]; then
  echo "No .venv found - run ./install.sh first" >&2
  exit 1
fi

if [ "${1:-}" = "calibrate" ]; then
  shift
  exec .venv/bin/python -m bdo_fishing_bot.tools.calibrate "$@"
fi
exec .venv/bin/python -m bdo_fishing_bot "$@"
