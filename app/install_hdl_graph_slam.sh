#!/usr/bin/env bash
set -euo pipefail
# Resolve this directory before changing working directories.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source /opt/ros/noetic/setup.bash
WS="${HOME}/catkin_ws"
mkdir -p "$WS/src"
sudo apt update
sudo apt install -y ros-noetic-geodesy ros-noetic-pcl-ros ros-noetic-nmea-msgs ros-noetic-libg2o libsuitesparse-dev libeigen3-dev
cd "$WS/src"
[[ -d ndt_omp ]] || git clone https://github.com/koide3/ndt_omp.git
[[ -d fast_gicp ]] || git clone https://github.com/SMRT-AIST/fast_gicp.git --recursive
[[ -d hdl_graph_slam ]] || git clone https://github.com/koide3/hdl_graph_slam.git
if [[ -d fast_gicp ]]; then git -C fast_gicp submodule update --init --recursive; fi
cp "$SCRIPT_DIR/hdl_graph_slam_gui.launch" "$WS/src/hdl_graph_slam/launch/hdl_graph_slam_gui.launch"
cd "$WS"
catkin_make -DCMAKE_BUILD_TYPE=Release
source "$WS/devel/setup.bash"
rospack profile
printf '\nInstalled packages:\n'
rospack find ndt_omp
rospack find fast_gicp
rospack find hdl_graph_slam
