# Historical variableV evaluation

This folder preserves selected machine-readable output from the local run `variableV_20260824_042242`.

- Reference: `rts_2026_07_15_09_02_02.traj`
- Evaluator: Trajectopy 4.3.3
- Matching: nearest temporal, maximum difference 0.05 s
- Alignment: rigid translation and rotation; no scale, estimated time shift or lever arm
- RPE range: 5–48.664 m in 5 m steps

The saved summary names the HDL profile `NDT_OMP + LM + Loops`, but the corresponding ROS log records `FAST_GICP` for `/scan_matching_odometry_nodelet/registration_method` and `/hdl_graph_slam_nodelet/registration_method`. Treat its HDL row as **FAST_GICP + LM + loops**. The original full run, raw sensor data, bags and generated maps are intentionally excluded.

The HDL comparison used only 24 temporally matched poses, substantially fewer than FAST-LIO2 (504) and LIO-SAM (166). Interpret that comparison cautiously. These results describe one dataset and do not establish a general ranking.
