#!/usr/bin/env bash
set -euo pipefail

# Trajectopy main currently requires Python >= 3.10. ROS Noetic on Ubuntu 20.04
# normally uses Python 3.8, so keep Trajectopy isolated from ROS in its own venv.
VENV="${TRAJECTOPY_VENV:-$HOME/.venvs/trajectory_lab_trajectopy}"
PY=""

version_ge_310() {
  "$1" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
}

for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1 && version_ge_310 "$(command -v "$candidate")"; then
    PY="$(command -v "$candidate")"
    break
  fi
done

if [[ -n "$PY" ]]; then
  echo "Using $($PY --version) at $PY"
  "$PY" -m venv "$VENV"
  "$VENV/bin/python" -m pip install --upgrade pip
  "$VENV/bin/python" -m pip install --upgrade trajectopy
else
  echo "No system Python >= 3.10 found. Installing an isolated Python 3.11 with uv..."
  if ! command -v uv >/dev/null 2>&1; then
    if command -v curl >/dev/null 2>&1; then
      curl -LsSf https://astral.sh/uv/install.sh | sh
    elif command -v wget >/dev/null 2>&1; then
      wget -qO- https://astral.sh/uv/install.sh | sh
    else
      echo "ERROR: curl or wget is required to install uv."
      exit 2
    fi
  fi

  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv installation finished but 'uv' is not on PATH. Open a new terminal and rerun this script."
    exit 2
  fi

  uv python install 3.11
  rm -rf "$VENV"
  uv venv --python 3.11 "$VENV"
  uv pip install --python "$VENV/bin/python" --upgrade trajectopy
fi

echo
echo "Checking Trajectopy API..."
"$VENV/bin/python" - <<'PY'
import inspect
import trajectopy as tpy
from trajectopy.visualization import mpl_plots

ate_sig = inspect.signature(tpy.ate)
required_ate = ["trajectory", "other", "processing_settings", "return_alignment", "align"]
missing_ate = [x for x in required_ate if x not in ate_sig.parameters]
if missing_ate:
    raise RuntimeError(f"Unsupported Trajectopy API; missing ate() parameters: {missing_ate}")

rpe_sig = inspect.signature(tpy.rpe)
required_rpe = ["trajectory", "other", "processing_settings"]
missing_rpe = [x for x in required_rpe if x not in rpe_sig.parameters]
if missing_rpe:
    raise RuntimeError(f"Unsupported Trajectopy API; missing rpe() parameters: {missing_rpe}")

for fn in ("plot_ate", "plot_ate_edf", "plot_ate_dof", "plot_rpe"):
    if not hasattr(mpl_plots, fn):
        raise RuntimeError(f"Unsupported Trajectopy plotting API; missing {fn}()")

print("Trajectopy:", getattr(tpy, "__version__", "unknown"))
print("ATE API: OK")
print("RPE API: OK")
print("Native plotting API: OK")
print("Python:", __import__("sys").version.split()[0])
print("Environment ready:", __import__("sys").executable)
PY

echo
echo "Done. The Trajectory Lab GUI will auto-detect:"
echo "  $VENV/bin/python"
echo "You can override it with TRAJECTOPY_PYTHON=/path/to/python if needed."
