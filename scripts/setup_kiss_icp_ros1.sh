#!/usr/bin/env bash
set -euo pipefail

WS="${1:-$HOME/catkin_ws}"
SRC="$WS/src"
TARGET="$SRC/kiss-icp"
TAG="v0.3.0"

source /opt/ros/noetic/setup.bash
mkdir -p "$SRC"

echo "KISS-ICP ROS1 setup"
echo "Workspace: $WS"

# Reuse an already discoverable ROS package when present.
if rospack find kiss_icp >/dev/null 2>&1; then
  FOUND="$(rospack find kiss_icp)"
  echo "Existing kiss_icp package found: $FOUND"
else
  if [[ -e "$TARGET" ]]; then
    echo "ERROR: $TARGET exists but kiss_icp is not discoverable." >&2
    echo "Move/remove that directory or build the existing checkout manually." >&2
    exit 1
  fi

  echo "Cloning official PRBonn/kiss-icp $TAG (last ROS1 release)..."
  git clone --depth 1 --branch "$TAG" https://github.com/PRBonn/kiss-icp.git "$TARGET"
fi

echo "Building workspace..."
cd "$WS"
catkin_make

source "$WS/devel/setup.bash"

PKG="$(rospack find kiss_icp)"
echo
echo "KISS-ICP ready: $PKG"
echo "Trajectory Lab launch profile:"
echo "  roslaunch kiss_icp odometry.launch topic:=/points_raw visualize:=false publish_odom_tf:=false min_range:=1.0 max_range:=100.0 deskew:=false"
echo "Odometry topic:"
echo "  /kiss/odometry"
