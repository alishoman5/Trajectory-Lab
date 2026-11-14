#!/usr/bin/env python3
"""Deterministic self-test for Trajectory Lab's evaluation layer.

This validates the GUI/evaluator independently from ROS and from any specific
SLAM algorithm.  All algorithms ultimately enter the evaluator as the same
.traj format, so the same synthetic estimate must produce the same metrics
regardless of the profile name.

Run with the dedicated Trajectopy interpreter:
  ~/.venvs/trajectory_lab_trajectopy/bin/python validate_evaluator.py
"""

import argparse
import json
import math
import struct
import tempfile
from pathlib import Path

import numpy as np

from compare_multi import (
    _ate_magnitude,
    build_processing_settings,
    evaluate_one,
)
from performance_analysis import (
    _relationship_trend_data,
    analyze_algorithm,
    ensure_reference_length,
    ensure_reference_speed,
    load_sbg_gyro,
    plot_results,
    read_traj,
    rigid_align,
)

try:
    import trajectopy as tpy
except Exception as exc:
    raise SystemExit(
        "FAIL: Trajectopy is not available in this Python environment. "
        "Run ./setup_trajectopy.sh first."
    ) from exc


APP_DIR = Path(__file__).resolve().parent
ALG_FILE = APP_DIR / "algorithms.json"


def write_traj(path, t, pos, name):
    t = np.asarray(t, dtype=float)
    pos = np.asarray(pos, dtype=float)
    step = np.linalg.norm(np.diff(pos, axis=0), axis=1)
    length = np.concatenate([[0.0], np.cumsum(step)])
    vel = np.column_stack([np.gradient(pos[:, k], t) for k in range(3)])

    with Path(path).open("w", encoding="utf-8") as f:
        f.write("#epsg 0\n")
        f.write(f"#name {name}\n")
        f.write("#nframe enu\n")
        f.write("#sorting time\n")
        f.write("#fields t,l,px,py,pz,vx,vy,vz\n")
        for i in range(len(t)):
            f.write(
                f"{t[i]:.9f},{length[i]:.9f},"
                f"{pos[i,0]:.9f},{pos[i,1]:.9f},{pos[i,2]:.9f},"
                f"{vel[i,0]:.9f},{vel[i,1]:.9f},{vel[i,2]:.9f}\n"
            )


def _sbg_frame(msg_id, payload, msg_class=0):
    return (
        bytes([0xFF, 0x5A, msg_id, msg_class])
        + struct.pack("<H", len(payload))
        + payload
        + b"\x00\x00"
        + bytes([0x33])
    )


def write_synthetic_sbg(path):
    """Create a minimal SBG ECom stream for parser validation."""
    chunks = []

    def utc_payload(sensor_us, minute, second):
        p = bytearray(21)
        struct.pack_into("<IH", p, 0, sensor_us, 0)
        struct.pack_into("<H", p, 6, 2026)
        struct.pack_into("<5B", p, 8, 7, 15, 9, minute, second)
        struct.pack_into("<I", p, 13, 0)
        struct.pack_into("<i", p, 17, 0)
        return bytes(p)

    chunks.append(_sbg_frame(2, utc_payload(0, 0, 0)))
    chunks.append(_sbg_frame(2, utc_payload(2_000_000, 0, 2)))

    for sensor_us, omega in [
        (0, 0.10),
        (500_000, 0.20),
        (1_000_000, 0.30),
        (1_500_000, 0.40),
        (2_000_000, 0.50),
    ]:
        p = bytearray(58)
        struct.pack_into("<IH", p, 0, sensor_us, 0)
        struct.pack_into("<3f", p, 6, 0.0, 0.0, 9.81)
        struct.pack_into("<3f", p, 18, 0.0, 0.0, omega)
        chunks.append(_sbg_frame(3, bytes(p)))

    Path(path).write_bytes(b"".join(chunks))


def rigid_transform(points):
    yaw = math.radians(27.0)
    pitch = math.radians(-4.0)
    rz = np.array([
        [math.cos(yaw), -math.sin(yaw), 0.0],
        [math.sin(yaw),  math.cos(yaw), 0.0],
        [0.0, 0.0, 1.0],
    ])
    ry = np.array([
        [math.cos(pitch), 0.0, math.sin(pitch)],
        [0.0, 1.0, 0.0],
        [-math.sin(pitch), 0.0, math.cos(pitch)],
    ])
    r = rz @ ry
    trans = np.array([12.0, -7.5, 1.8])
    return (r @ np.asarray(points).T).T + trans


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def near(a, b, tol, message):
    if abs(float(a) - float(b)) > tol:
        raise AssertionError(f"{message}: {a} vs {b} (tol {tol})")


def profile_checks():
    profiles = json.loads(ALG_FILE.read_text(encoding="utf-8"))
    ids = [p.get("id") for p in profiles]
    require(all(ids), "every algorithm profile must have an id")
    require(len(ids) == len(set(ids)), "algorithm profile ids must be unique")
    for p in profiles:
        if p.get("configured", False):
            require(bool(p.get("launch_command")), f"{p['id']} has no launch command")
            require(bool(p.get("odom_topic")), f"{p['id']} has no odometry topic")
        if p.get("result_mode") == "hdl_graph_dump":
            require(bool(p.get("optimized_topic")), "HDL graph-dump profile needs optimized_topic")
    return profiles


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default="", help="Optional JSON report path")
    args = ap.parse_args()

    report = {"trajectopy_version": str(getattr(tpy, "__version__", "unknown")), "checks": []}

    def passed(name, detail=""):
        report["checks"].append({"name": name, "status": "PASS", "detail": detail})
        print(f"PASS  {name}" + (f" — {detail}" if detail else ""))

    profiles = profile_checks()
    passed("algorithm profile schema", f"{len(profiles)} profiles checked")

    x_fit, y_fit, bin_x, bin_y = _relationship_trend_data(
        np.arange(12, dtype=float),
        2.0 * np.arange(12, dtype=float) + 1.0,
        bins=6,
    )
    require(x_fit is not None and y_fit is not None, "linear trend was not generated")
    require(len(bin_x) >= 2 and len(bin_y) == len(bin_x), "binned-mean curve was not generated")
    near(y_fit[0], 1.0, 1e-9, "linear trend intercept is incorrect")
    near(y_fit[-1], 23.0, 1e-9, "linear trend slope is incorrect")
    passed("motion trend curves", "linear fit and binned means generated deterministically")

    mag = _ate_magnitude(np.array([[3.0, 4.0, 0.0], [-1.0, -2.0, -2.0]]), expected_samples=2)
    require(np.allclose(mag, [5.0, 3.0]), "3D ATE magnitude helper is incorrect")
    require(np.all(mag >= 0.0), "3D ATE magnitude must never be negative")
    passed("3D ATE magnitude", "component deviations reduce to one non-negative magnitude")

    settings = build_processing_settings(0.05, 5.0, 20.0, 5.0, True)
    est = settings.alignment.estimation_settings
    require(est.translation_x and est.translation_y and est.translation_z, "translation alignment disabled")
    require(est.rotation_x and est.rotation_y and est.rotation_z, "rotation alignment disabled")
    require(not est.scale, "scale must remain disabled")
    require(not est.time_shift, "time-shift estimation must remain disabled")
    require(not est.leverarm_x and not est.leverarm_y and not est.leverarm_z, "lever arm estimation must remain disabled")
    passed("evaluation policy", "SE(3) alignment; no scale, time shift or lever arm")

    # Smooth, non-degenerate ~70 m 3D reference trajectory.
    t = np.linspace(0.0, 60.0, 601)
    ref = np.column_stack([
        1.10 * t,
        2.4 * np.sin(t / 5.0) + 0.4 * np.sin(t / 1.7),
        0.25 * np.sin(t / 8.0),
    ])

    with tempfile.TemporaryDirectory(prefix="trajectory_lab_validation_") as td:
        root = Path(td)
        ref_path = root / "reference.traj"
        write_traj(ref_path, t, ref, "synthetic_reference")
        ref_traj = tpy.Trajectory.from_file(str(ref_path))

        # Case 1: a pure rigid coordinate-frame change must disappear after SE(3) alignment.
        rigid_path = root / "rigid_only.traj"
        write_traj(rigid_path, t, rigid_transform(ref), "rigid_only")
        rigid_out = root / "rigid_out"; rigid_out.mkdir()
        rigid_metrics, _, _, _ = evaluate_one(
            ref_traj, rigid_path, "Rigid-only", "rigid_only", settings, rigid_out
        )
        require(rigid_metrics["ate_mean_m"] < 1e-5, "rigid transform was not removed by alignment")
        require(rigid_metrics["rms_3d_m"] < 1e-5, "rigid transform left residual RMS error")
        passed("rigid-alignment invariance", f"ATE mean {rigid_metrics['ate_mean_m']:.3e} m")

        # Case 2: non-rigid shape error must remain after alignment.
        distortion = np.column_stack([
            0.018 * np.sin(t / 2.3),
            0.055 * np.sin(t / 3.1),
            0.020 * np.cos(t / 4.2),
        ])
        distorted_base = ref + distortion
        distorted = rigid_transform(distorted_base)
        distorted_path = root / "distorted.traj"
        write_traj(distorted_path, t, distorted, "distorted")
        distorted_out = root / "distorted_out"; distorted_out.mkdir()
        distorted_metrics, _, _, _ = evaluate_one(
            ref_traj, distorted_path, "Distorted", "distorted", settings, distorted_out
        )

        independently_aligned, _, _ = rigid_align(distorted, ref)
        independent_error = np.linalg.norm(independently_aligned - ref, axis=1)
        independent_mean = float(np.mean(independent_error))
        near(
            distorted_metrics["ate_mean_m"], independent_mean, 2e-4,
            "Trajectopy ATE disagrees with independent rigid-alignment calculation"
        )
        require(distorted_metrics["ate_mean_m"] > 0.01, "known non-rigid distortion vanished unexpectedly")
        passed(
            "independent ATE cross-check",
            f"Trajectopy {distorted_metrics['ate_mean_m']:.5f} m vs independent {independent_mean:.5f} m"
        )

        # The focused diagnostics must also work end-to-end on the same synthetic files.
        ref_diag = read_traj(ref_path)
        ensure_reference_length(ref_diag)
        ensure_reference_speed(ref_diag)
        synthetic_angular = {
            "t": t,
            "angular_velocity": 0.15 + 0.08 * np.sin(np.linspace(0.0, 8.0, len(t))),
        }
        diag = analyze_algorithm(
            ref_diag,
            distorted_path,
            {"id": "synthetic", "name": "Synthetic"},
            angular=synthetic_angular,
        )
        require("speed_ate_correlation" in diag, "speed correlation missing from diagnostics")
        require("acceleration_ate_correlation" in diag, "acceleration correlation missing from diagnostics")
        require("angular_velocity_ate_correlation" in diag, "angular-velocity correlation missing from diagnostics")
        require(
            len(diag["_plot"]["acceleration"]) == diag["moving_poses"],
            "acceleration diagnostic sample count mismatch"
        )
        require(
            len(diag["_plot"]["angular_velocity"]) == diag["moving_poses"],
            "angular-velocity diagnostic sample count mismatch"
        )
        diag_out = root / "diagnostic_plots"; diag_out.mkdir()
        diag_paths = plot_results(diag_out, [diag])
        require(
            set(diag_paths) == {"ate_distance", "ate_speed", "ate_acceleration", "ate_angular_velocity", "segment_heatmap"},
            f"unexpected diagnostic plot set: {sorted(diag_paths)}"
        )
        require(all(Path(p).is_file() for p in diag_paths.values()), "one or more diagnostic plots were not written")
        passed(
            "focused motion diagnostics",
            "distance, speed, acceleration, angular velocity and failure-heatmap outputs generated"
        )

        # Validate the pure-Python SBG UTC/gyro parser used by saved-run diagnostics.
        sbg_path = root / "synthetic_sbg.bin"
        write_synthetic_sbg(sbg_path)
        sbg = load_sbg_gyro(sbg_path)
        require(sbg["samples"] == 5, f"unexpected synthetic SBG sample count: {sbg['samples']}")
        require(np.all(np.isfinite(sbg["angular_velocity"])), "non-finite SBG angular velocity")
        require(float(np.max(sbg["angular_velocity"])) > 0.25, "SBG gyro magnitude was not parsed")
        passed("SBG angular-velocity parser", "UTC timestamps and body gyro magnitudes decoded")

        # Case 3: scale is deliberately NOT estimated. A 2% scale error should remain
        # visible in both global position error and local distance drift.
        scaled_path = root / "scaled.traj"
        write_traj(scaled_path, t, rigid_transform(ref * 1.02), "scaled_2pct")
        scaled_out = root / "scaled_out"; scaled_out.mkdir()
        scaled_metrics, _, _, _ = evaluate_one(
            ref_traj, scaled_path, "Scale +2%", "scaled", settings, scaled_out
        )
        require(scaled_metrics["ate_mean_m"] > 0.05, "2% scale error was incorrectly removed")
        rpe = scaled_metrics.get("rpe_position")
        require(rpe is not None and 1.0 < float(rpe) < 3.0, f"unexpected RPE for 2% scale error: {rpe}")
        passed("no-scale policy", f"2% scale error remains; mean RPE {float(rpe):.3f}%")

        # The evaluator must not depend on algorithm identity. Feed the SAME .traj
        # through every configured/profile label and verify identical ATE.
        per_profile = {}
        for p in profiles:
            out_dir = root / ("profile_" + p["id"]); out_dir.mkdir()
            m, _, _, _ = evaluate_one(
                ref_traj, distorted_path, p.get("name", p["id"]), p["id"], settings, out_dir
            )
            per_profile[p["id"]] = float(m["ate_mean_m"])
        vals = list(per_profile.values())
        require(max(vals) - min(vals) < 1e-10, f"metrics depend on algorithm profile: {per_profile}")
        passed("algorithm-independent evaluator", f"same trajectory identical across {len(per_profile)} profiles")

        # Basic exported-metric consistency.
        require(distorted_metrics["matched_samples"] == len(t), "unexpected matched-pose count")
        require(distorted_metrics["ate"]["pos_mean_m"] == distorted_metrics["ate_mean_m"], "ATE alias mismatch")
        require(distorted_metrics["ate"]["pos_rms_m"] == distorted_metrics["rms_3d_m"], "RMS alias mismatch")
        passed("summary consistency", "GUI summary aliases match native numeric summary")

    report["status"] = "PASS"
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("\nTrajectory Lab evaluator self-test: PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\nTrajectory Lab evaluator self-test: FAIL\n{type(exc).__name__}: {exc}")
        raise SystemExit(1)
