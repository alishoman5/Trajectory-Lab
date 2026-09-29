#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WS="${1:-$HOME/catkin_ws}"
for directory in LIO-SAM/config FAST_LIO/config FAST_LIO/launch hdl_graph_slam/launch; do
  [[ -d "$WS/src/$directory" ]] || { echo "Missing package directory: $WS/src/$directory" >&2; exit 1; }
done
STAMP="$(date +%Y%m%dT%H%M%S)-$$"
install_file() {
  local src="$1" dst="$2"
  if [[ -e "$dst" ]]; then
    cp -p -- "$dst" "$dst.trajectory-lab-backup-$STAMP"
    echo "Backup: $dst.trajectory-lab-backup-$STAMP"
  fi
  cp -- "$src" "$dst"
  echo "Installed: $dst"
}
install_file "$ROOT/config/lio-sam/params.yaml" "$WS/src/LIO-SAM/config/params.yaml"
install_file "$ROOT/config/fast-lio2/ouster128_gui.yaml" "$WS/src/FAST_LIO/config/ouster128_gui.yaml"
install_file "$ROOT/launch/fast-lio2/mapping_ouster128_gui.launch" "$WS/src/FAST_LIO/launch/mapping_ouster128_gui.launch"
install_file "$ROOT/app/hdl_graph_slam_gui.launch" "$WS/src/hdl_graph_slam/launch/hdl_graph_slam_gui.launch"
echo "Profiles installed. Validate the rig extrinsics and run a known dataset before reporting results."
