# Clean-machine setup for Trajectory Lab

This guide is for a teammate who wants to run the same Trajectory Lab GUI on another Ubuntu machine.

## 1. Target environment

The project was developed for:

- Ubuntu 20.04
- ROS 1 Noetic
- catkin workspace at `~/catkin_ws`
- Livox driver workspace at `~/ws_livox` when FAST-LIO2 is used
- Python 3 for the ROS-side tools
- a separate Python >= 3.10 virtual environment for Trajectopy

Do not replace ROS Noetic's system Python with the Trajectopy environment.

## 2. Clone this repository

```bash
cd ~
git clone https://github.com/alishoman5/Trajectory-Lab.git
cd Trajectory-Lab
```

## 3. Install the GUI/runtime Python packages

```bash
sudo apt update
sudo apt install -y python3-pyqt5 python3-pip libxcb-cursor0
python3 -m pip install --user numpy matplotlib
```

ROS bag/message packages come from ROS Noetic rather than pip.

## 4. Install the SLAM backends

The GUI launches external ROS packages; those packages are not vendored into this repository.

Install and build the algorithms you plan to use:

- LIO-SAM: https://github.com/TixiaoShan/LIO-SAM
- FAST-LIO2 / FAST_LIO: https://github.com/hku-mars/FAST_LIO
- Livox ROS driver, required by the FAST_LIO build: https://github.com/Livox-SDK/livox_ros_driver
- hdl_graph_slam: https://github.com/koide3/hdl_graph_slam
- ndt_omp: https://github.com/koide3/ndt_omp

KISS-ICP is currently only a placeholder profile in `app/algorithms.json`; it is not ready until a ROS wrapper publishing `nav_msgs/Odometry` is configured.

After building, verify that ROS can find the packages you intend to run:

```bash
source /opt/ros/noetic/setup.bash
source ~/ws_livox/devel/setup.bash 2>/dev/null || true
source ~/catkin_ws/devel/setup.bash

rospack find lio_sam
rospack find fast_lio
rospack find hdl_graph_slam
```

Only check the packages you actually installed.

## 5. Install this project's algorithm profiles

The repository contains the project-specific LIO-SAM, FAST-LIO2 and HDL configuration used by the GUI.

From the repository root:

```bash
bash scripts/install_profiles.sh ~/catkin_ws
```

The installer checks the target packages and backs up existing target configuration files before copying the project profiles.

## 6. Install Trajectopy in its own environment

From the application folder:

```bash
cd ~/Trajectory-Lab/app
chmod +x setup_trajectopy.sh
./setup_trajectopy.sh
```

The GUI automatically looks for:

```text
~/.venvs/trajectory_lab_trajectopy/bin/python
```

You can also point it to another compatible interpreter:

```bash
export TRAJECTOPY_PYTHON=/path/to/venv/bin/python
```

## 7. Start the GUI

```bash
cd ~/Trajectory-Lab/app

source /opt/ros/noetic/setup.bash
source ~/ws_livox/devel/setup.bash 2>/dev/null || true
source ~/catkin_ws/devel/setup.bash

chmod +x run_gui.sh
./run_gui.sh
```

## 8. Dataset files expected by the GUI

For the current Ouster + SBG workflow select:

- Ouster `.pcap`
- matching Ouster metadata `.json`
- SBG Ellipse-D raw `.bin`
- RTS ground-truth `.traj`

The sensor conversion code is specific to the current project rig and synchronization assumptions. Do not assume it is a generic converter for unrelated sensors.

## 9. Evaluation and Performance Insights

A normal run:

1. converts/reuses the synchronized sensor bag,
2. runs each selected algorithm,
3. exports each estimated trajectory,
4. compares estimates with RTS using Trajectopy,
5. produces ATE/RPE results,
6. runs the additional Performance Insights diagnostics.

The newer diagnostics include:

- true 3D ATE magnitude versus time,
- moving-only speed sensitivity,
- low/medium/high speed comparison,
- 5 m local drift,
- worst 5 m failure segments,
- failure heatmap,
- dataset history.

Stationary start/end periods are removed from the speed analysis with the current 0.30 m/s threshold.

You can also use **Load / Analyze saved run** in the Results page to generate the new diagnostics from an older completed run without replaying the ROS bags.

## 10. Important portability notes

- The provided extrinsic/sensor settings belong to the project rig.
- The Ouster timestamp conversion assumes the recorded PPS/NMEA configuration in the metadata.
- The GUI does not install ROS or the external SLAM repositories by itself.
- Results should only be compared when all algorithms use the same synchronized dataset and the same RTS reference/evaluation policy.
- Large ROS bags and generated run outputs should stay outside Git.

If the GUI starts but one algorithm fails, inspect that algorithm's log in the generated run folder first.
