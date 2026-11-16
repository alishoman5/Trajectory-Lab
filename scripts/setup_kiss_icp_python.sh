#!/usr/bin/env bash
set -euo pipefail

VENV="${1:-$HOME/.venvs/trajectory_lab_kiss_icp}"

python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip setuptools wheel

# Pin the Python KISS-ICP release whose config schema includes registration
# controls used by Trajectory Lab's config.yml.
"$VENV/bin/python" -m pip install "kiss-icp[all]==1.3.0"

echo
echo "KISS-ICP Python environment ready:"
echo "  $VENV/bin/python"
"$VENV/bin/python" - <<'PY'
import kiss_icp
from ouster.sdk import open_source
print("kiss_icp version:", getattr(kiss_icp, "__version__", "unknown"))
print("ouster-sdk import: OK")
PY
