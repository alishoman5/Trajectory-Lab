#!/usr/bin/env bash
set -e

# The GUI itself is ROS-agnostic. ROS environments are sourced only inside the
# pipeline when a ROS-based algorithm (LIO-SAM / FAST-LIO / HDL Graph SLAM)
# actually needs them. Direct Python KISS-ICP therefore runs with no ROS setup.
cd "$(dirname "$0")"
exec python3 trajectory_lab.py
