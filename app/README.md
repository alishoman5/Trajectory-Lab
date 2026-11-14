# Trajectory Lab GUI — focused trajectory evaluation

ROS1 Noetic toolbox for running multiple LiDAR/LiDAR-inertial trajectory estimators on the same synchronized dataset and evaluating them with **Trajectopy**. RTS is the preferred reference. If RTS is not provided, the GUI automatically builds a local ENU reference from the SBG binary log.

## Included algorithm profiles

- **LIO-SAM** — configured
- **FAST-LIO2** — configured
- **HDL Graph SLAM (NDT_OMP + LM + Loops)** — configured
- **KISS-ICP** — placeholder until its ROS wrapper is configured

## Evaluation reference

Reference priority:

1. **RTS trajectory** when an RTS `.traj` is supplied.
2. **SBG GPS1 raw GNSS** position/velocity when RTS is blank.
3. **SBG GNSS/INS EKF_NAV** only when raw GPS1 position is not present in the SBG log.

The SBG fallback converter reads UTC timing from the same binary log, converts WGS84 latitude/longitude/height to a local ENU frame, and resamples the reference to 10 Hz for temporal matching. It also saves the reported 1σ horizontal/vertical positioning accuracy in `sbg_gnss_reference_metadata.json`.

GNSS/GNSS-INS is a fallback reference, not equivalent to RTS ground truth. ATE/RPE values are limited by the reference positioning uncertainty.

## Evaluation policy

The comparison stage delegates temporal matching, rigid 6-DoF alignment, ATE and distance-based RPE to Trajectopy.

- nearest temporal matching
- rigid translation + rotation alignment
- no scale estimation
- no time-shift estimation
- no lever-arm estimation
- RPE defaults: 5–50 m in 5 m steps

The validated project environment uses **Trajectopy 4.3.3**. The setup script pins this version because newer Trajectopy releases changed the plotting API.

## Focused Results UI

The GUI intentionally shows only outputs that answer a concrete evaluation question.

### Overview
Answers: **Is the trajectory accurate overall?**

Shows:
- ATE mean
- ATE RMS
- ATE max
- position RPE
- matched poses
- algorithm ranking by ATE mean

### Motion Diagnostics
Answers: **Under which motion conditions does the error increase?**

Shows:
- moving-only ATE
- speed ↔ ATE correlation
- reference acceleration ↔ ATE correlation
- gravity-compensated SBG linear-acceleration ↔ ATE correlation
- measured SBG angular-velocity ↔ ATE correlation
- low / medium / high-speed ATE

The correlations are diagnostic associations, not proof of causation.

### Failure Segments
Answers: **Where are the weakest sections?**

Shows the worst 5 m sections with:
- mean and maximum ATE
- mean speed
- mean acceleration
- number of poses

## Focused plots

The GUI shows seven plots:

1. Trajectory vs Reference
2. ATE Along Route
3. RPE vs Distance
4. ATE vs Speed
5. ATE vs Reference Acceleration
6. ATE vs IMU Acceleration
7. ATE vs Angular Velocity
8. Failure Heatmap

The three motion relationship plots keep the raw scatter points and add a dashed linear trend line plus a solid equal-width binned-mean curve. These curves are descriptive aids only and do not imply causation.

Detailed Trajectopy properties, aligned trajectories, covariance/correlation plots and per-algorithm audit files are still preserved under:

```text
comparison/raw/
```

They are available for verification without cluttering the main results view.

## Speed analysis

Stationary start/end periods are removed using a 0.30 m/s threshold.

Current speed bins:

- Low: 0.30–1.20 m/s
- Medium: 1.20–1.60 m/s
- High: >1.60 m/s

reference acceleration magnitude is derived from the RTS velocity trajectory and is kept as an external ground-truth motion descriptor.

SBG IMU linear acceleration is derived from the recorded body-frame accelerometer specific force. The SBG EKF quaternion rotates the measurement from body to NED, the project converts NED to ENU, and gravity is removed before taking the 3D magnitude. This makes the IMU-acceleration diagnostic closer to the measurement stream used by LIO-SAM than reference acceleration.

Angular velocity is taken directly from the recorded SBG IMU body gyro and reported as the 3D gyro magnitude in rad/s. For older saved runs, the analyzer first checks run metadata and otherwise uses the single `.bin` file beside the RTS trajectory when that identification is unambiguous.

## Evaluator validation

A deterministic self-test is included:

```bash
~/.venvs/trajectory_lab_trajectopy/bin/python validate_evaluator.py
```

The GUI also exposes **Run evaluator self-test** on the Results page.

The test verifies:

- algorithm profile schema
- correct non-negative 3D ATE magnitude
- rigid SE(3) alignment invariance
- independent ATE calculation against Trajectopy
- no-scale policy using a known 2% scale error
- identical metrics for the same trajectory under every algorithm profile
- speed/acceleration/failure diagnostic generation
- consistency between native metrics and GUI summary aliases

GitHub Actions additionally runs static checks and a headless GUI smoke test.

## Install GUI dependency

```bash
sudo apt update
sudo apt install python3-pyqt5
```

If Qt reports an `xcb-cursor0` problem:

```bash
sudo apt install libxcb-cursor0
```

## Install/verify Trajectopy

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

1. Select or auto-detect PCAP, JSON and SBG BIN. Add RTS `.traj` when available; otherwise leave RTS blank to use the SBG GNSS fallback.
2. Validate the dataset and confirm the intended reference source.
3. Select the configured algorithms.
4. Run them against the same synchronized sensor bag.
5. Inspect Overview first.
6. Locate weak regions with ATE Along Route and Failure Heatmap.
7. Compare error against speed and acceleration.
8. Use raw audit files only when a result needs deeper verification.

**Load / Analyze saved run** can generate the focused diagnostics from an existing completed run without replaying ROS bags.
