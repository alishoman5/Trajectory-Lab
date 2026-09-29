# Trajectory Lab GUI — Trajectopy ATE + RPE

ROS1 Noetic toolbox for running multiple LiDAR/LiDAR-inertial trajectory estimators on the same synchronized dataset and evaluating them against RTS with **Trajectopy**.

## Included algorithm profiles

- **LIO-SAM** — configured
- **FAST-LIO2** — configured
- **HDL Graph SLAM (NDT_OMP + LM + Loops)** — configured
  - NDT_OMP scan matching
  - NDT_OMP loop verification
  - loop closures enabled
  - Levenberg-Marquardt + CHOLMOD (`lm_var_cholmod`) graph optimization
  - final optimized graph poses are evaluated, not raw `/odom`
- **KISS-ICP** — placeholder profile until its ROS wrapper is configured

## Evaluation

The comparison stage delegates temporal matching, rigid 6-DoF alignment, ATE and RPE to Trajectopy. Scale and time-shift estimation are disabled because sensor synchronization is handled upstream.

The GUI displays the complete Trajectopy ATE and RPE property dictionaries, RPE statistics by distance, and alignment output. Native result CSVs, aligned trajectories, alignment files, JSON/TXT summaries and official Trajectopy plots are written to each run folder.

See `TRAJECTOPY_EVALUATION.md` for the exact policy and output list.

## RPE defaults for the campus-scale datasets

- min pair distance: 5 m
- max pair distance: 50 m
- step: 5 m
- all overlapping pose pairs: enabled

Distance-domain position RPE is reported by Trajectopy in `%`; rotation RPE is `deg/100m` when reference orientation exists.

## Sensor workflow

The supplied converters target the current rig:

- Ouster OS1-128
- SBG Ellipse-D raw ECom `.bin`
- PPS/NMEA-synchronized Ouster timestamps
- RTS `.traj` ground truth

## Install GUI dependency

```bash
sudo apt update
sudo apt install python3-pyqt5
```

If Qt reports an `xcb-cursor0` problem:

```bash
sudo apt install libxcb-cursor0
```

## Install/verify Trajectopy once

```bash
chmod +x setup_trajectopy.sh
./setup_trajectopy.sh
```

Trajectopy is kept in its own Python environment so ROS Noetic's Python environment is not replaced.

## Run

```bash
source /opt/ros/noetic/setup.bash
source ~/ws_livox/devel/setup.bash
source ~/catkin_ws/devel/setup.bash
./run_gui.sh
```

## Recommended workflow

1. Dataset → select or auto-detect PCAP, JSON, SBG BIN and RTS `.traj`.
2. Validate dataset.
3. Algorithms → select configured algorithms.
4. Run & Compare → choose temporal matching and RPE distance settings.
5. Run selected algorithms.
6. Results → inspect Overview, All ATE outputs, All RPE outputs, Alignment outputs and RPE by distance.
7. Open run folder for native Trajectopy CSV/JSON/TXT/plots and algorithm logs.

## Results UI (clarified version)

The Results screen now separates the evaluation into a compact overview, ATE details,
RPE details, alignment parameters and RPE-by-distance tables. Plot previews use concise
algorithm names and high-resolution figures. The XY view is shown in a local coordinate
frame relative to the first RTS point so large UTM offsets do not compress the plot.
Native Trajectopy plots and CSV/JSON outputs are still preserved in the run folder.
