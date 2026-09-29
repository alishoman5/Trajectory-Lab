# Export inspection

Inspected 2026-09-29 from the user's Windows export `E:/c`.

## Source selection

Application source: `Trajectory_Lab_GUI_HDL_NDT_LM_Loops_Trajectopy_ATE_RPE_UI_Fixed/trajectory_lab_gui_hdl_trajectopy`.

This bundle includes Trajectopy ATE/RPE, local-coordinate previews, RTS-preferring selection, and NDT_OMP HDL settings. Its name and contents agree with the intended handoff, but this does not prove it was the last version actually executed on Ubuntu.

LIO-SAM parameters and FAST-LIO2 settings/launcher were imported from `catkin_ws/src`. Application files are byte-for-byte copies; `import-checksums.json` records their import hashes. Raw data, recordings, generated results, other GUI versions, upstream source trees and unrelated personal exports were excluded.

## Findings requiring an Ubuntu validation run

1. The exported workspace's `hdl_graph_slam_gui.launch` still uses FAST_GICP, while the selected GUI bundle uses NDT_OMP. Its launch command resolves the workspace file by package name. Installing the selected launcher is necessary to obtain the intended NDT_OMP configuration. Existing results cannot be relabeled as NDT_OMP on the basis of the GUI name.
2. LIO-SAM has zero translation and an approximately 5-degree Z rotation in both extrinsic rotation matrices. FAST-LIO2 has zero translation and identity rotation, with extrinsic estimation disabled. Frame conventions must be checked before deciding whether these configurations are consistent. The matrices were preserved, not corrected by guesswork.
3. `bag_to_traj.py` omits orientation. Rotational ATE/RPE cannot be claimed for its outputs, even if reference orientations later become available.
4. RTS auto-detection prefers `rts*.traj`, but falls back to the first other `.traj` if no RTS-named file exists. The user must verify the selected file.
5. HDL graph export follows a fixed flush delay after playback; code inspection alone does not establish that all backend processing has finished.
6. The setup scripts install unpinned dependency versions. Installed Ubuntu package versions and upstream Git revisions were not captured, so exact environment reproduction is not yet established.
7. The imported Trajectopy setup script can delete its target venv in the uv fallback path. Do not run it against an environment containing unrelated work; a manual isolated setup is documented instead.
8. The aggregate RPE field named `median_position_drift` is calculated as the median of per-distance medians, not the median of all individual pose-pair errors. Use native/per-distance outputs and disclose aggregation when reporting it.

## Validation status

JSON and launch XML can be checked during packaging, and import checksums can establish file integrity. No ROS algorithm run, sensor conversion, calibration validation or numerical evaluation has been performed in this Windows session. No new accuracy claims were added.

Before publication: choose visibility and application licensing/credits. Before advertising reproducibility: record the working dependency versions and rerun a known dataset on Ubuntu with the intended launch files.
