#!/usr/bin/env bash
# The supported entry point for the Tier 2 credibility campaign: an
# E_COEFFICIENT sweep, a grid-convergence study, and a full-duration run,
# chained behind one command (see solit2/engines/fds/campaign.py for what
# each step does and how the whole thing survives being interrupted).
#
# This script owns exactly the two OS-level guards the campaign itself does
# not: refusing to start on battery power, and holding the machine awake for
# a run that is hours long. Everything else -- resumability, the up-front
# rate estimate, the three steps themselves -- is `solit2 fds-campaign`,
# called below, and is unit-tested there; this script is deliberately thin
# and stays that way.
#
# Usage:
#   scripts/tier2_campaign.sh DESIGN --grid-dx H1 H2 H3 --grid-t-end SECONDS \
#       --out OUT_DIR [--e-anchor c4 c5] [--e 0.1 0.2 0.4 0.8] [--dx 0.6] \
#       [--allow-battery]
#
# Every flag after the design is forwarded to `solit2 fds-campaign` verbatim,
# except --allow-battery, which this script consumes itself.
set -euo pipefail

allow_battery=0
forwarded=()
for arg in "$@"; do
  if [[ "$arg" == "--allow-battery" ]]; then
    allow_battery=1
  else
    forwarded+=("$arg")
  fi
done

if [[ "$(uname -s)" == "Darwin" ]] && command -v pmset >/dev/null 2>&1; then
  if pmset -g batt | grep -q "Battery Power" && [[ "$allow_battery" -ne 1 ]]; then
    echo "refusing to start: this machine is running on battery power." >&2
    echo "A Tier 2 campaign is hours long. Plug in, or pass --allow-battery" >&2
    echo "if you mean to run it unplugged anyway." >&2
    exit 1
  fi
fi

if ! command -v caffeinate >/dev/null 2>&1; then
  echo "warning: caffeinate is not on this machine (this script's sleep guard is" >&2
  echo "macOS-only), so the run is not protected against system sleep." >&2
  exec uv run solit2 fds-campaign "${forwarded[@]}"
fi

exec caffeinate -i -s uv run solit2 fds-campaign "${forwarded[@]}"
