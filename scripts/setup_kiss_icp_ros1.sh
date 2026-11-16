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

# Prefer the managed checkout in this workspace and pin it to the last ROS1
# release so the launch file and parameters used by Trajectory Lab are stable.
if [[ -d "$TARGET/.git" ]]; then
  echo "Existing managed KISS-ICP checkout found: $TARGET"
  git -C "$TARGET" fetch --tags --depth 1 origin "$TAG"
  git -C "$TARGET" checkout -f "$TAG"
elif [[ -e "$TARGET" ]]; then
  echo "ERROR: $TARGET exists but is not a git checkout." >&2
  echo "Move/remove it, then rerun this script." >&2
  exit 1
else
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
echo "  roslaunch kiss_icp odometry.launch topic:=/points_raw visualize:=false publish_odom_tf:=false min_range:=1.0 max_range:=50.0 voxel_size:=0.5 deskew:=false"
echo "Odometry topic:"
echo "  /kiss/odometry"
