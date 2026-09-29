#!/usr/bin/env python3
"""Evaluate multiple trajectory estimates with Trajectopy.

The evaluator delegates matching, rigid alignment, ATE and RPE to Trajectopy.
It preserves Trajectopy's native result files and property dictionaries, and
creates only lightweight combined preview plots for the GUI.
"""

import argparse
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

try:
    import trajectopy as tpy
    from trajectopy.core.settings import PairDistanceUnit
    from trajectopy.visualization import mpl_plots
except Exception as exc:
    raise RuntimeError(
        "Trajectopy could not be imported. Run ./setup_trajectopy.sh from the GUI folder first."
    ) from exc


def safe_version():
    return str(getattr(tpy, "__version__", "unknown"))


def json_safe(value):
    """Convert numpy/scalar containers to JSON-safe values without changing meaning."""
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    return value


def build_processing_settings(max_dt, rpe_min, rpe_max, rpe_step, rpe_all_pairs=True):
    settings = tpy.ProcessingSettings()
    settings.matching.method = tpy.MatchingMethod.NEAREST_TEMPORAL
    settings.matching.max_time_diff = float(max_dt)

    # Rigid SE(3) alignment policy: 6 DoF, no scale, no time shift, no lever arm.
    est = settings.alignment.estimation_settings
    est.translation_x = True
    est.translation_y = True
    est.translation_z = True
    est.rotation_x = True
    est.rotation_y = True
    est.rotation_z = True
    est.scale = False
    est.time_shift = False
    est.leverarm_x = False
    est.leverarm_y = False
    est.leverarm_z = False
    est.sensor_rotation = False

    # Distance-domain RPE. Trajectopy reports position drift in % and rotation
    # drift in deg/100m for PairDistanceUnit.METER.
    rel = settings.relative_comparison
    rel.pair_min_distance = float(rpe_min)
    rel.pair_max_distance = float(rpe_max)
    rel.pair_distance_step = float(rpe_step)
    rel.pair_distance_unit = PairDistanceUnit.METER
    rel.use_all_pose_pairs = bool(rpe_all_pairs)
    return settings


def effective_rpe_range(ref_traj, req_min, req_max, req_step):
    """Make requested distance buckets valid for short trajectories.

    Trajectopy's package defaults (100..800 m) are too large for our campus
    datasets (~tens of metres), so the GUI exposes explicit values.  This
    function only caps impossible values; it does not alter the RPE formula.
    """
    try:
        length = float(ref_traj.path_lengths[-1] - ref_traj.path_lengths[0])
    except Exception:
        xyz = np.asarray(ref_traj.positions.xyz, dtype=float)
        length = float(np.linalg.norm(np.diff(xyz, axis=0), axis=1).sum()) if len(xyz) > 1 else 0.0

    if length <= 0:
        raise RuntimeError("Reference trajectory has zero path length; RPE cannot be computed.")

    rmin = max(0.01, float(req_min))
    rstep = max(0.01, float(req_step))
    # Keep a margin so pose pairs exist near the upper bucket.
    feasible_max = max(0.01, length * 0.90)
    rmax = min(float(req_max), feasible_max)

    if rmax <= rmin:
        rmin = max(0.1, min(1.0, length * 0.10))
        rstep = rmin
        rmax = max(rmin, length * 0.80)

    return rmin, rmax, rstep, length


def ate_numeric_summary(ate_result):
    has_rot = bool(getattr(ate_result, "has_orientation", False))
    d = {
        "pos_mean_m": float(ate_result.pos_ate),
        "pos_rms_m": float(ate_result.pos_dev_rms),
        "pos_min_m": float(ate_result.pos_dev_min),
        "pos_median_m": float(ate_result.pos_dev_median),
        "pos_max_m": float(ate_result.pos_dev_max),
        "pos_std_m": float(ate_result.pos_dev_std),
        "bias_x_m": float(ate_result.pos_bias_x),
        "bias_y_m": float(ate_result.pos_bias_y),
        "bias_z_m": float(ate_result.pos_bias_z),
        "rms_x_m": float(ate_result.pos_rms_x),
        "rms_y_m": float(ate_result.pos_rms_y),
        "rms_z_m": float(ate_result.pos_rms_z),
        "bias_along_m": float(ate_result.pos_bias_along),
        "bias_cross_h_m": float(ate_result.pos_bias_cross_h),
        "bias_cross_v_m": float(ate_result.pos_bias_cross_v),
        "rms_along_m": float(ate_result.pos_rms_along),
        "rms_cross_h_m": float(ate_result.pos_rms_cross_h),
        "rms_cross_v_m": float(ate_result.pos_rms_cross_v),
        "has_rotation": has_rot,
    }
    if has_rot:
        d.update({
            "rot_mean_deg": float(np.rad2deg(ate_result.rot_ate)),
            "rot_rms_deg": float(np.rad2deg(ate_result.rot_dev_rms)),
            "rot_min_deg": float(np.rad2deg(ate_result.rot_dev_min)),
            "rot_median_deg": float(np.rad2deg(ate_result.rot_dev_median)),
            "rot_max_deg": float(np.rad2deg(ate_result.rot_dev_max)),
            "rot_std_deg": float(np.rad2deg(ate_result.rot_dev_std)),
            "rot_rms_roll_deg": float(np.rad2deg(ate_result.rot_rms_x)),
            "rot_rms_pitch_deg": float(np.rad2deg(ate_result.rot_rms_y)),
            "rot_rms_yaw_deg": float(np.rad2deg(ate_result.rot_rms_z)),
            "rot_bias_roll_deg": float(np.rad2deg(ate_result.rot_bias_x)),
            "rot_bias_pitch_deg": float(np.rad2deg(ate_result.rot_bias_y)),
            "rot_bias_yaw_deg": float(np.rad2deg(ate_result.rot_bias_z)),
        })
    else:
        for k in (
            "rot_mean_deg","rot_rms_deg","rot_min_deg","rot_median_deg","rot_max_deg","rot_std_deg",
            "rot_rms_roll_deg","rot_rms_pitch_deg","rot_rms_yaw_deg",
            "rot_bias_roll_deg","rot_bias_pitch_deg","rot_bias_yaw_deg",
        ):
            d[k] = None
    return d


def rpe_numeric_summary(rpe_result):
    has_rot = bool(getattr(rpe_result, "has_rot_dev", False))
    pos_mean = list(map(float, rpe_result.pos_dev_mean))
    pos_min = list(map(float, rpe_result.pos_dev_min))
    pos_max = list(map(float, rpe_result.pos_dev_max))
    pos_median = list(map(float, rpe_result.pos_dev_median))
    pos_std = list(map(float, rpe_result.pos_std))
    mean_dist = list(map(float, rpe_result.mean_pair_distances))
    pairs = [int(x) for x in rpe_result.num_pairs]

    d = {
        "pair_distance_unit": str(rpe_result.pair_distance_unit),
        "position_drift_unit": str(rpe_result.pos_drift_unit),
        "rotation_drift_unit": str(rpe_result.rot_drift_unit),
        "num_pairs_total": int(len(rpe_result)),
        "mean_position_drift": float(rpe_result.pos_rpe),
        "min_position_drift": float(np.min(pos_min)) if pos_min else None,
        "median_position_drift": float(np.median(pos_median)) if pos_median else None,
        "max_position_drift": float(np.max(pos_max)) if pos_max else None,
        "has_rotation": has_rot,
        "mean_rotation_drift_deg_per_100m": float(np.rad2deg(rpe_result.rot_rpe)) if has_rot else None,
        "per_distance": [],
    }

    rot_mean = list(map(float, rpe_result.rot_dev_mean)) if has_rot else []
    rot_min = list(map(float, rpe_result.rot_dev_min)) if has_rot else []
    rot_max = list(map(float, rpe_result.rot_dev_max)) if has_rot else []
    rot_median = list(map(float, rpe_result.rot_dev_median)) if has_rot else []
    rot_std = list(map(float, rpe_result.rot_std)) if has_rot else []

    n = min(len(mean_dist), len(pos_mean), len(pairs))
    for i in range(n):
        row = {
            "distance_m": mean_dist[i],
            "pairs": pairs[i],
            "pos_mean": pos_mean[i],
            "pos_min": pos_min[i],
            "pos_median": pos_median[i],
            "pos_max": pos_max[i],
            "pos_std": pos_std[i],
            "rot_mean_deg_per_100m": float(np.rad2deg(rot_mean[i])) if has_rot and i < len(rot_mean) else None,
            "rot_min_deg_per_100m": float(np.rad2deg(rot_min[i])) if has_rot and i < len(rot_min) else None,
            "rot_median_deg_per_100m": float(np.rad2deg(rot_median[i])) if has_rot and i < len(rot_median) else None,
            "rot_max_deg_per_100m": float(np.rad2deg(rot_max[i])) if has_rot and i < len(rot_max) else None,
            "rot_std_deg_per_100m": float(np.rad2deg(rot_std[i])) if has_rot and i < len(rot_std) else None,
        }
        d["per_distance"].append(row)
    return d


def evaluate_one(ref_traj, est_path, name, alg_id, processing_settings, out):
    est_traj = tpy.Trajectory.from_file(str(est_path))

    ate_result, alignment_result = tpy.ate(
        trajectory=est_traj,
        other=ref_traj,
        processing_settings=processing_settings,
        return_alignment=True,
        align=True,
    )

    if len(ate_result.abs_dev.pos_dev) < 3:
        raise RuntimeError(
            f"Trajectopy matched only {len(ate_result.abs_dev.pos_dev)} poses for {name}. "
            "Verify timestamps or increase Max time match."
        )

    # RPE is computed by Trajectopy on the ATE-aligned/matched trajectory.
    # A global rigid transform does not change relative pose error, and this
    # keeps the same evaluated trajectory available for auditing.
    rpe_result = tpy.rpe(
        trajectory=ate_result.trajectory,
        other=ref_traj,
        processing_settings=processing_settings,
    )

    # Replace Trajectopy's auto-generated "estimate vs. reference-filename"
    # labels with the concise algorithm name for tables, files and native plots.
    ate_result.name = name
    try:
        ate_result.trajectory.name = name
    except Exception:
        pass
    rpe_result.name = name
    try:
        alignment_result.name = name
    except Exception:
        pass
    if len(rpe_result) == 0:
        raise RuntimeError(
            f"Trajectopy produced zero RPE pose pairs for {name}. "
            "Reduce the RPE minimum/maximum distance in Run & Compare."
        )

    # Native Trajectopy files.
    ate_file = out / f"{alg_id}_trajectopy_ate.csv"
    rpe_file = out / f"{alg_id}_trajectopy_rpe.csv"
    aligned_file = out / f"{alg_id}_trajectopy_aligned.traj"
    alignment_file = out / f"{alg_id}_trajectopy_alignment.csv"
    ate_result.to_file(str(ate_file), mode="w")
    rpe_result.to_file(str(rpe_file), mode="w")
    ate_result.trajectory.to_file(str(aligned_file))
    try:
        alignment_file.unlink(missing_ok=True)
    except TypeError:
        if alignment_file.exists(): alignment_file.unlink()
    alignment_result.to_file(str(alignment_file))

    ate_props = dict(ate_result.property_dict)
    rpe_props = dict(rpe_result.property_dict)
    ate_num = ate_numeric_summary(ate_result)
    rpe_num = rpe_numeric_summary(rpe_result)

    # Preserve the alignment result as well. Trajectopy exposes the complete
    # enabled/disabled parameter set and covariance through AlignmentParameters.
    pos_params = alignment_result.position_parameters
    rot_params = alignment_result.rotation_parameters
    alignment_props = {
        "Name": str(alignment_result.name),
        "Converged": bool(alignment_result.converged),
        "Position parameters": json_safe(pos_params.to_dict(enabled_only=False)),
        "Enabled position parameters": list(pos_params.to_string_list(enabled_only=True)),
        "All position parameters": list(pos_params.to_string_list(enabled_only=False)),
        "Sim3 matrix": json_safe(pos_params.sim3_matrix),
    }
    try:
        alignment_props["Sensor rotation parameters"] = json_safe(rot_params.to_dict(enabled_only=False))
        alignment_props["All sensor rotation parameters"] = list(rot_params.to_string_list(enabled_only=False))
    except Exception:
        alignment_props["Sensor rotation parameters"] = {}

    alignment_json = out / f"{alg_id}_trajectopy_alignment.json"
    alignment_json.write_text(json.dumps(json_safe(alignment_props), indent=2), encoding="utf-8")

    all_metrics = {
        "algorithm": name,
        "id": alg_id,
        "trajectopy_version": safe_version(),
        "ATE_property_dict": ate_props,
        "RPE_property_dict": rpe_props,
        "Alignment": alignment_props,
        "ATE_numeric": ate_num,
        "RPE_numeric": rpe_num,
    }
    all_json = out / f"{alg_id}_trajectopy_all_metrics.json"
    all_json.write_text(json.dumps(json_safe(all_metrics), indent=2), encoding="utf-8")
    all_txt = out / f"{alg_id}_trajectopy_all_metrics.txt"
    with all_txt.open("w", encoding="utf-8") as f:
        f.write(f"Trajectopy {safe_version()} — {name}\n\n[ATE]\n")
        for k, v in ate_props.items():
            f.write(f"{k}: {v}\n")
        f.write("\n[RPE]\n")
        for k, v in rpe_props.items():
            f.write(f"{k}: {v}\n")

    metrics = {
        "id": alg_id,
        "name": name,
        "evaluation_backend": "Trajectopy",
        "trajectopy_version": safe_version(),
        "matching_method": "NEAREST_TEMPORAL",
        "max_time_diff_s": float(processing_settings.matching.max_time_diff),
        "alignment": "6DoF translation+rotation; scale=false; time_shift=false",
        "matched_samples": int(len(ate_result.abs_dev.pos_dev)),
        "ate": ate_num,
        "rpe": rpe_num,
        "ate_properties": ate_props,
        "rpe_properties": rpe_props,
        "alignment_properties": alignment_props,
        # Compatibility aliases.
        "ate_mean_m": ate_num["pos_mean_m"],
        "rms_3d_m": ate_num["pos_rms_m"],
        "median_error_m": ate_num["pos_median_m"],
        "max_error_m": ate_num["pos_max_m"],
        "std_error_m": ate_num["pos_std_m"],
        "rmse_x_m": ate_num["rms_x_m"],
        "rmse_y_m": ate_num["rms_y_m"],
        "rmse_z_m": ate_num["rms_z_m"],
        "ate_rmse_m": ate_num["pos_rms_m"],
        "mean_error_m": ate_num["pos_mean_m"],
        "rpe_position": rpe_num["mean_position_drift"],
        "rpe_position_unit": rpe_num["position_drift_unit"],
        "rpe_rotation_deg_per_100m": rpe_num["mean_rotation_drift_deg_per_100m"],
        "rpe_pairs": rpe_num["num_pairs_total"],
        "source_traj": str(est_path),
        "trajectopy_ate_file": str(ate_file),
        "trajectopy_rpe_file": str(rpe_file),
        "trajectopy_aligned_traj": str(aligned_file),
        "trajectopy_alignment_file": str(alignment_file),
        "trajectopy_alignment_json": str(alignment_json),
        "trajectopy_all_metrics_json": str(all_json),
        "trajectopy_all_metrics_txt": str(all_txt),
    }

    return metrics, ate_result, rpe_result, alignment_result


def save_native_plots(out, ate_results, rpe_results, alignment_results):
    """Save Trajectopy's official Matplotlib evaluation visualizations.

    Each call below delegates plot generation to trajectopy.visualization.mpl_plots.
    A failure of an optional plot is non-fatal; the numeric/native CSV results
    are still the source of truth.
    """
    paths = {}

    def save_fig(key, filename, fig, dpi=170):
        if fig is None:
            return
        p = out / filename
        fig.savefig(p, dpi=dpi, bbox_inches="tight")
        plt.close(fig)
        paths[key] = str(p)

    # Multi-algorithm ATE/RPE plots.
    try:
        save_fig("ate", "trajectopy_ate.png", mpl_plots.plot_ate(ate_results))
    except Exception as e:
        print(f"WARNING: Trajectopy plot_ate failed: {e}")

    try:
        save_fig("ate_edf", "trajectopy_ate_edf.png", mpl_plots.plot_ate_edf(ate_results))
    except Exception as e:
        print(f"WARNING: Trajectopy plot_ate_edf failed: {e}")

    try:
        save_fig("ate_3d", "trajectopy_ate_3d.png", mpl_plots.plot_ate_3d(ate_results))
    except Exception as e:
        print(f"WARNING: Trajectopy plot_ate_3d failed: {e}")

    try:
        save_fig("ate_bars_position", "trajectopy_ate_bars_position.png", mpl_plots.plot_ate_bars(ate_results, mode="positions"))
    except Exception as e:
        print(f"WARNING: Trajectopy plot_ate_bars positions failed: {e}")

    if any(getattr(a, "has_orientation", False) for a in ate_results):
        try:
            save_fig("ate_bars_rotation", "trajectopy_ate_bars_rotation.png", mpl_plots.plot_ate_bars(ate_results, mode="rotations"))
        except Exception as e:
            print(f"WARNING: Trajectopy plot_ate_bars rotations failed: {e}")

    try:
        fig_metric, fig_time = mpl_plots.plot_rpe(rpe_results)
        save_fig("rpe", "trajectopy_rpe_metric.png", fig_metric)
        save_fig("rpe_time", "trajectopy_rpe_time.png", fig_time)
    except Exception as e:
        print(f"WARNING: Trajectopy plot_rpe failed: {e}")

    # Per-algorithm ATE visualizations.
    for ate in ate_results:
        safe = "".join(c if c.isalnum() else "_" for c in ate.name).strip("_").lower()
        try:
            save_fig(f"ate_dof_{safe}", f"trajectopy_ate_dof_{safe}.png", mpl_plots.plot_ate_dof(ate), dpi=160)
        except Exception as e:
            print(f"WARNING: Trajectopy plot_ate_dof failed for {ate.name}: {e}")
        try:
            save_fig(f"ate_hist_{safe}", f"trajectopy_ate_hist_{safe}.png", mpl_plots.plot_compact_ate_hist(ate), dpi=160)
        except Exception as e:
            print(f"WARNING: Trajectopy plot_compact_ate_hist failed for {ate.name}: {e}")
        try:
            pos_fig, rot_fig = mpl_plots.scatter_ate(ate)
            save_fig(f"ate_scatter_position_{safe}", f"trajectopy_ate_scatter_position_{safe}.png", pos_fig, dpi=160)
            save_fig(f"ate_scatter_rotation_{safe}", f"trajectopy_ate_scatter_rotation_{safe}.png", rot_fig, dpi=160)
        except Exception as e:
            print(f"WARNING: Trajectopy scatter_ate failed for {ate.name}: {e}")

    # Alignment covariance/correlation plots, when the estimated covariance is valid.
    for alignment in alignment_results:
        safe = "".join(c if c.isalnum() else "_" for c in alignment.name).strip("_").lower()
        try:
            fig = mpl_plots.plot_covariance_heatmap(alignment.position_parameters, enabled_only=True)
            save_fig(f"alignment_covariance_{safe}", f"trajectopy_alignment_covariance_{safe}.png", fig, dpi=160)
        except Exception as e:
            print(f"WARNING: Trajectopy covariance heatmap failed for {alignment.name}: {e}")
        try:
            fig = mpl_plots.plot_correlation_heatmap(alignment.position_parameters, enabled_only=True)
            save_fig(f"alignment_correlation_{safe}", f"trajectopy_alignment_correlation_{safe}.png", fig, dpi=160)
        except Exception as e:
            print(f"WARNING: Trajectopy correlation heatmap failed for {alignment.name}: {e}")

    return paths


def save_gui_plots(out, ref_traj, ate_results, rpe_results, display_names):
    """Create clean high-resolution GUI previews from Trajectopy result objects.

    Trajectopy remains the evaluation backend. These figures only present its
    aligned trajectories and error arrays with shorter labels and local axes.
    Native Trajectopy plots are still exported separately.
    """
    paths = {}
    ref_xyz = np.asarray(ref_traj.positions.xyz, dtype=float)
    ref_t = np.asarray(ref_traj.timestamps, dtype=float)
    origin_xy = ref_xyz[0, :2].copy()
    origin_z = float(ref_xyz[0, 2])

    # 1) XY trajectory comparison in a local frame. This avoids large UTM
    # offsets and makes centimetre/decimetre deviations visually readable.
    fig, ax = plt.subplots(figsize=(12.5, 7.2))
    ax.plot(ref_xyz[:, 0] - origin_xy[0], ref_xyz[:, 1] - origin_xy[1],
            linewidth=2.8, label="RTS Ground Truth")
    for label, ate in zip(display_names, ate_results):
        xyz = np.asarray(ate.trajectory.positions.xyz, dtype=float)
        ax.plot(xyz[:, 0] - origin_xy[0], xyz[:, 1] - origin_xy[1],
                linewidth=1.8, label=label)
    ax.set_title("Aligned Trajectories vs RTS Ground Truth", fontsize=15, pad=12)
    ax.set_xlabel("East displacement from RTS start [m]", fontsize=11)
    ax.set_ylabel("North displacement from RTS start [m]", fontsize=11)
    ax.axis("equal")
    ax.grid(True, alpha=0.30)
    ax.legend(loc="best", fontsize=9, frameon=True)
    fig.tight_layout()
    xy_path = out / "combined_xy.png"
    fig.savefig(xy_path, dpi=220, bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)
    paths["xy"] = str(xy_path)

    # 2) Position ATE versus time. Values come directly from Trajectopy's
    # AbsoluteDeviation result; only visualization is custom.
    fig, ax = plt.subplots(figsize=(12.5, 6.4))
    for label, ate in zip(display_names, ate_results):
        err = np.asarray(ate.abs_dev.pos_dev, dtype=float)
        ts = np.asarray(ate.trajectory.timestamps, dtype=float)
        n = min(len(err), len(ts))
        if n == 0:
            continue
        ax.plot(ts[:n] - ts[0], err[:n], linewidth=1.7, label=label)
    ax.set_title("Absolute Trajectory Error (ATE) vs Time", fontsize=15, pad=12)
    ax.set_xlabel("Time from first matched pose [s]", fontsize=11)
    ax.set_ylabel("3D position error [m]", fontsize=11)
    ax.grid(True, alpha=0.30)
    ax.legend(loc="best", fontsize=9, frameon=True)
    fig.tight_layout()
    ate_path = out / "gui_ate_vs_time.png"
    fig.savefig(ate_path, dpi=220, bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)
    paths["ate"] = str(ate_path)

    # 3) Distance-domain RPE. Trajectopy reports position drift in percent
    # when PairDistanceUnit.METER is used.
    fig, ax = plt.subplots(figsize=(12.5, 6.4))
    for label, rpe in zip(display_names, rpe_results):
        dist = np.asarray(rpe.mean_pair_distances, dtype=float)
        drift = np.asarray(rpe.pos_dev_mean, dtype=float)
        n = min(len(dist), len(drift))
        if n == 0:
            continue
        ax.plot(dist[:n], drift[:n], marker="o", linewidth=1.7, markersize=4, label=label)
    ax.set_title("Relative Pose Error (RPE) vs Travel Distance", fontsize=15, pad=12)
    ax.set_xlabel("Pose-pair distance [m]", fontsize=11)
    ax.set_ylabel("Mean position drift [%]", fontsize=11)
    ax.grid(True, alpha=0.30)
    ax.legend(loc="best", fontsize=9, frameon=True)
    fig.tight_layout()
    rpe_path = out / "gui_rpe_vs_distance.png"
    fig.savefig(rpe_path, dpi=220, bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)
    paths["rpe"] = str(rpe_path)

    # 4) Elevation comparison relative to the RTS start height.
    fig, ax = plt.subplots(figsize=(12.5, 6.2))
    ax.plot(ref_t - ref_t[0], ref_xyz[:, 2] - origin_z, linewidth=2.6, label="RTS Ground Truth")
    for label, ate in zip(display_names, ate_results):
        ts = np.asarray(ate.trajectory.timestamps, dtype=float)
        xyz = np.asarray(ate.trajectory.positions.xyz, dtype=float)
        ax.plot(ts - ref_t[0], xyz[:, 2] - origin_z, linewidth=1.7, label=label)
    ax.set_title("Elevation Comparison", fontsize=15, pad=12)
    ax.set_xlabel("Time from RTS start [s]", fontsize=11)
    ax.set_ylabel("Height relative to RTS start [m]", fontsize=11)
    ax.grid(True, alpha=0.30)
    ax.legend(loc="best", fontsize=9, frameon=True)
    fig.tight_layout()
    z_path = out / "combined_z.png"
    fig.savefig(z_path, dpi=220, bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)
    paths["z"] = str(z_path)

    return paths


def main():
    ap = argparse.ArgumentParser(description="Compare trajectories using Trajectopy ATE + RPE")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--max-dt", type=float, default=0.05)
    ap.add_argument("--rpe-min", type=float, default=5.0)
    ap.add_argument("--rpe-max", type=float, default=50.0)
    ap.add_argument("--rpe-step", type=float, default=5.0)
    ap.add_argument("--rpe-all-pairs", type=int, choices=(0, 1), default=1)
    args = ap.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    ref_path = Path(manifest["rts"])
    ref_traj = tpy.Trajectory.from_file(str(ref_path))
    ref_xyz = np.asarray(ref_traj.positions.xyz, dtype=float)
    ref_t = np.asarray(ref_traj.timestamps, dtype=float)

    rpe_min, rpe_max, rpe_step, ref_length = effective_rpe_range(
        ref_traj, args.rpe_min, args.rpe_max, args.rpe_step
    )
    processing_settings = build_processing_settings(
        args.max_dt, rpe_min, rpe_max, rpe_step, bool(args.rpe_all_pairs)
    )
    processing_settings.to_file(str(out / "trajectopy_processing_settings.json"))

    eval_meta = {
        "trajectopy_version": safe_version(),
        "reference": str(ref_path),
        "reference_path_length_m": ref_length,
        "matching_method": "NEAREST_TEMPORAL",
        "max_time_diff_s": args.max_dt,
        "alignment": "rigid 6DoF translation+rotation; scale=false; time_shift=false",
        "rpe": {
            "pair_distance_unit": "METER",
            "requested_min_m": args.rpe_min,
            "requested_max_m": args.rpe_max,
            "requested_step_m": args.rpe_step,
            "effective_min_m": rpe_min,
            "effective_max_m": rpe_max,
            "effective_step_m": rpe_step,
            "use_all_pose_pairs": bool(args.rpe_all_pairs),
            "position_unit": "% (m per 100 m)",
            "rotation_unit": "deg/100m when orientation is available",
        },
    }
    (out / "trajectopy_evaluation_metadata.json").write_text(json.dumps(eval_meta, indent=2), encoding="utf-8")

    results = []
    ate_results = []
    rpe_results = []
    alignment_results = []

    for est in manifest["estimates"]:
        name = est["name"]
        alg_id = est["id"]
        est_path = Path(est["traj"])
        if not est_path.is_file():
            raise RuntimeError(f"Missing exported trajectory for {name}: {est_path}")

        metrics, ate_result, rpe_result, alignment_result = evaluate_one(
            ref_traj, est_path, name, alg_id, processing_settings, out
        )
        metrics["bag"] = est.get("bag", "")
        metrics["topic"] = est.get("topic", "")
        metrics["traj"] = str(est_path)
        results.append(metrics)
        ate_results.append(ate_result)
        rpe_results.append(rpe_result)
        alignment_results.append(alignment_result)

    # Native Trajectopy position ATE is the primary rank metric.
    results.sort(key=lambda x: x["ate_mean_m"])
    for rank, item in enumerate(results, 1):
        item["rank"] = rank

    (out / "summary_metrics.json").write_text(json.dumps(json_safe(results), indent=2), encoding="utf-8")

    overview_fields = [
        "rank", "name", "ate_mean_m", "rms_3d_m", "median_error_m", "max_error_m",
        "rpe_position", "rpe_position_unit", "rpe_rotation_deg_per_100m", "rpe_pairs",
        "matched_samples", "trajectopy_version",
    ]
    with (out / "summary_metrics.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=overview_fields)
        w.writeheader()
        for r in results:
            w.writerow({k: r.get(k) for k in overview_fields})

    with (out / "summary_metrics.txt").open("w", encoding="utf-8") as f:
        f.write(f"Evaluation backend: Trajectopy {safe_version()}\n")
        f.write("Matching: NEAREST_TEMPORAL\n")
        f.write(f"Max time difference: {args.max_dt:.6f} s\n")
        f.write("Alignment: translation + rotation (6 DoF), scale disabled, time-shift disabled\n")
        f.write(f"RPE distance buckets: {rpe_min:.3f} .. {rpe_max:.3f} m, step {rpe_step:.3f} m\n")
        f.write("RPE position unit: % (metres drift per 100 m)\n")
        f.write("RPE rotation unit: deg/100m when reference orientation exists\n\n")
        for r in results:
            rot_ate = r["ate"].get("rot_mean_deg")
            rot_rpe = r["rpe"].get("mean_rotation_drift_deg_per_100m")
            f.write(
                f"#{r['rank']} {r['name']}\n"
                f"ATE position mean: {r['ate_mean_m']:.6f} m\n"
                f"ATE position RMS: {r['rms_3d_m']:.6f} m\n"
                f"ATE rotation mean: {rot_ate if rot_ate is not None else 'N/A'} deg\n"
                f"RPE position mean: {r['rpe_position']:.6f} {r['rpe_position_unit']}\n"
                f"RPE rotation mean: {rot_rpe if rot_rpe is not None else 'N/A'} deg/100m\n"
                f"RPE pose pairs: {r['rpe_pairs']}\n"
                f"Matched poses: {r['matched_samples']}\n\n"
            )

    # Exact property dictionaries from Trajectopy for convenient cross-algorithm audit.
    full_props = {
        r["name"]: {
            "ATE": r["ate_properties"],
            "RPE": r["rpe_properties"],
            "Alignment": r["alignment_properties"],
        }
        for r in results
    }
    (out / "trajectopy_all_properties.json").write_text(json.dumps(full_props, indent=2), encoding="utf-8")

    native_plots = save_native_plots(out, ate_results, rpe_results, alignment_results)

    # Machine-readable index of everything produced by this Trajectopy run.
    output_manifest = {
        "evaluation_backend": f"Trajectopy {safe_version()}",
        "reference": str(ref_path),
        "algorithms": {
            r["name"]: {
                "ate_csv": r["trajectopy_ate_file"],
                "rpe_csv": r["trajectopy_rpe_file"],
                "aligned_trajectory": r["trajectopy_aligned_traj"],
                "alignment_csv": r["trajectopy_alignment_file"],
                "alignment_json": r["trajectopy_alignment_json"],
                "all_metrics_json": r["trajectopy_all_metrics_json"],
                "all_metrics_txt": r["trajectopy_all_metrics_txt"],
            }
            for r in results
        },
        "plots": native_plots,
        "summary_files": [
            str(out / "summary_metrics.json"),
            str(out / "summary_metrics.csv"),
            str(out / "summary_metrics.txt"),
            str(out / "trajectopy_all_properties.json"),
            str(out / "trajectopy_processing_settings.json"),
            str(out / "trajectopy_evaluation_metadata.json"),
        ],
    }
    (out / "trajectopy_output_manifest.json").write_text(
        json.dumps(json_safe(output_manifest), indent=2), encoding="utf-8"
    )

    # Clean, high-resolution GUI previews based on Trajectopy result objects.
    # Native Trajectopy figures above remain available in the run folder.
    display_names = [est["name"] for est in manifest["estimates"]]
    gui_plots = save_gui_plots(out, ref_traj, ate_results, rpe_results, display_names)
    native_plots.update({f"gui_{k}": v for k, v in gui_plots.items()})

    # Compatibility alias for old GUI versions.
    clean_ate = gui_plots.get("ate")
    if clean_ate and Path(clean_ate).is_file():
        Path(out / "combined_error.png").write_bytes(Path(clean_ate).read_bytes())
    elif "ate" in native_plots:
        Path(out / "combined_error.png").write_bytes(Path(native_plots["ate"]).read_bytes())

    print("\n========== TRAJECTOPY RANKING ==========")
    print(f"Trajectopy version: {safe_version()}")
    print(f"RPE: {rpe_min:.2f}..{rpe_max:.2f} m step {rpe_step:.2f} m")
    for r in results:
        rot = r.get("rpe_rotation_deg_per_100m")
        rot_text = f"{rot:.4f} deg/100m" if rot is not None else "N/A"
        print(
            f"#{r['rank']} {r['name']}: ATE(mean) {r['ate_mean_m']:.4f} m | "
            f"RMS3D {r['rms_3d_m']:.4f} m | RPE-pos {r['rpe_position']:.4f} "
            f"{r['rpe_position_unit']} | RPE-rot {rot_text}"
        )
    print("=========================================")
    print(out / "summary_metrics.json")


if __name__ == "__main__":
    main()
