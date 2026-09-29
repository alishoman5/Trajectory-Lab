# Trajectopy evaluation backend

This GUI uses **Trajectopy** (`gereon-t/trajectopy`) as the evaluation backend. The GUI does not recompute ATE/RPE with a custom metric implementation.

## Evaluation policy

For every algorithm result exported as `.traj`:

1. Load RTS reference and estimate with `trajectopy.Trajectory.from_file()`.
2. Match poses with `MatchingMethod.NEAREST_TEMPORAL` and the GUI `Trajectopy max time match [s]` threshold.
3. Compute ATE with `trajectopy.ate(..., align=True, return_alignment=True)`.
4. Alignment estimates X/Y/Z translation and roll/pitch/yaw rotation (rigid 6-DoF).
5. Scale, time-shift, lever-arm and sensor-rotation estimation are disabled.
6. Compute distance-domain RPE with `trajectopy.rpe()`.
7. Rank algorithms by Trajectopy `ATEResult.pos_ate` (mean 3D position deviation).

## RPE settings

The upstream Trajectopy distance defaults (100–800 m) are too large for short campus trajectories, so the GUI exposes:

- RPE minimum pair distance (default 5 m)
- RPE maximum pair distance (default 50 m)
- RPE distance step (default 5 m)
- use all overlapping pose pairs (default enabled)

The evaluator caps an impossible maximum distance to the reference path length while preserving the requested step as far as possible.

For distance-domain RPE, Trajectopy reports:

- position drift in `%` (normalized drift per 100 m)
- rotation drift in `deg/100m` when both trajectories contain orientation

If the RTS `.traj` has positions but no orientation, rotation ATE/RPE is correctly shown as **N/A**; it is not synthesized.

## Results visible in the GUI

The Results page contains:

- Overview: ATE mean/RMS/median/max, RPE position, RPE rotation, RPE pair count, matched poses
- **All ATE outputs**: every entry from `ATEResult.property_dict`
- **All RPE outputs**: every entry from `RPEResult.property_dict`, including dynamic per-distance values
- **Alignment outputs**: full Trajectopy alignment parameter/covariance metadata and convergence state
- **RPE by distance**: pair count plus min/mean/median/max/std drift for every RPE distance bucket

## Files exported for every algorithm

Each comparison folder contains native/auditable Trajectopy data:

- `<algorithm>_trajectopy_ate.csv` — full per-pose ATE deviations exported by Trajectopy
- `<algorithm>_trajectopy_rpe.csv` — full RPE samples exported by Trajectopy
- `<algorithm>_trajectopy_aligned.traj` — aligned estimated trajectory
- `<algorithm>_trajectopy_alignment.csv` — native alignment result
- `<algorithm>_trajectopy_alignment.json` — readable alignment parameters/covariance metadata
- `<algorithm>_trajectopy_all_metrics.json`
- `<algorithm>_trajectopy_all_metrics.txt`

Cross-algorithm files:

- `summary_metrics.json/csv/txt`
- `trajectopy_all_properties.json`
- `trajectopy_processing_settings.json`
- `trajectopy_evaluation_metadata.json`
- `trajectopy_output_manifest.json`

## Official Trajectopy plots saved when supported

- `trajectopy_ate.png`
- `trajectopy_ate_edf.png`
- `trajectopy_ate_3d.png`
- `trajectopy_ate_bars_position.png`
- `trajectopy_ate_bars_rotation.png` (only if rotation deviations exist)
- `trajectopy_rpe_metric.png`
- `trajectopy_rpe_time.png` (for time-domain RPE, if used)
- per-algorithm `trajectopy_ate_dof_*.png`
- per-algorithm `trajectopy_ate_hist_*.png`
- per-algorithm `trajectopy_ate_scatter_position_*.png`
- per-algorithm `trajectopy_ate_scatter_rotation_*.png` (if orientation exists)
- alignment covariance/correlation heatmaps when the estimated covariance supports them

The GUI also keeps `combined_xy.png` and `combined_z.png` as convenience previews; metric values still come from Trajectopy.

## Separate Python environment

Trajectopy currently needs a newer Python than the ROS Noetic Python commonly used on Ubuntu 20.04. Keep Trajectopy isolated from ROS:

```bash
chmod +x setup_trajectopy.sh
./setup_trajectopy.sh
```

The GUI auto-detects:

```text
~/.venvs/trajectory_lab_trajectopy/bin/python
```

Override if required:

```bash
export TRAJECTOPY_PYTHON=/path/to/python
```
