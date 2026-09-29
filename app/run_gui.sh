#!/usr/bin/env bash
set -e
source /opt/ros/noetic/setup.bash
if [[ -f "$HOME/catkin_ws/devel/setup.bash" ]]; then
  source "$HOME/catkin_ws/devel/setup.bash"
fi
cd "$(dirname "$0")"
exec python3 trajectory_lab.py
