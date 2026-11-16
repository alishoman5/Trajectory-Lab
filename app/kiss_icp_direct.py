#!/usr/bin/env python3
"""Run KISS-ICP directly on an Ouster PCAP and export Trajectory Lab .traj.

No ROS, ROS master, PointCloud2, or rosbag is used in this path.
"""

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

from kiss_icp.config import load_config
from kiss_icp.datasets.ouster import OusterDataloader
from kiss_icp.kiss_icp import KissICP


def find_key_recursive(obj, key):
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for value in obj.values():
            found = find_key_recursive(value, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = find_key_recursive(value, key)
            if found is not None:
                return found
    return None


def write_traj(path, timestamps, poses, name="KISS-ICP"):
    positions = np.asarray(poses, dtype=float)[:, :3, 3]
    step = np.linalg.norm(np.diff(positions, axis=0), axis=1)
    lengths = np.concatenate([[0.0], np.cumsum(step)])

    # Trajectory Lab currently evaluates position trajectories. Velocities are
    # derived from the direct KISS positions/timestamps for the .traj format.
    if len(timestamps) >= 3:
        vel = np.column_stack([
            np.gradient(positions[:, k], timestamps) for k in range(3)
        ])
    else:
        vel = np.zeros_like(positions)

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        f.write("#epsg 0\n")
        f.write(f"#name {name}\n")
        f.write("#nframe enu\n")
        f.write("#sorting time\n")
        f.write("#fields t,l,px,py,pz,vx,vy,vz\n")
        for i in range(len(timestamps)):
            f.write(
                f"{timestamps[i]:.9f},{lengths[i]:.9f},"
                f"{positions[i,0]:.9f},{positions[i,1]:.9f},{positions[i,2]:.9f},"
                f"{vel[i,0]:.9f},{vel[i,1]:.9f},{vel[i,2]:.9f}\n"
            )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pcap", required=True)
    ap.add_argument("--metadata", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--metrics-out", default="")
    args = ap.parse_args()

    for label, value in (
        ("PCAP", args.pcap),
        ("metadata", args.metadata),
        ("config", args.config),
    ):
        if not Path(value).is_file():
            raise RuntimeError(f"{label} file not found: {value}")

    metadata_json = json.loads(Path(args.metadata).read_text(encoding="utf-8"))
    timestamp_mode = find_key_recursive(metadata_json, "timestamp_mode")
    leap_seconds = find_key_recursive(metadata_json, "nmea_leap_seconds")

    if timestamp_mode != "TIME_FROM_SYNC_PULSE_IN":
        raise RuntimeError(
            "Expected Ouster timestamp_mode TIME_FROM_SYNC_PULSE_IN; "
            f"got {timestamp_mode!r}."
        )
    if leap_seconds is None:
        raise RuntimeError("nmea_leap_seconds not found in Ouster metadata.")

    config = load_config(Path(args.config))
    dataset = OusterDataloader(data_dir=args.pcap, meta=args.metadata)
    odometry = KissICP(config=config)

    poses = []
    runtimes_ms = []

    print("KISS-ICP direct Python pipeline")
    print("==============================")
    print(f"PCAP        : {args.pcap}")
    print(f"Metadata    : {args.metadata}")
    print(f"Config      : {args.config}")
    print(f"Scans       : {len(dataset)}")
    print(f"Deskew      : {config.data.deskew}")
    print(f"Range       : {config.data.min_range} .. {config.data.max_range} m")
    print(f"Voxel size  : {config.mapping.voxel_size} m")
    print(f"Leap seconds: {leap_seconds}")

    for idx in range(len(dataset)):
        frame, point_timestamps = dataset[idx]
        tic = time.perf_counter()
        odometry.register_frame(frame, point_timestamps)
        runtimes_ms.append((time.perf_counter() - tic) * 1000.0)
        poses.append(np.asarray(odometry.last_pose, dtype=float).copy())
        if (idx + 1) % 50 == 0 or idx + 1 == len(dataset):
            print(f"Processed {idx + 1}/{len(dataset)} scans")

    poses = np.asarray(poses, dtype=float)
    raw_timestamps = np.asarray(dataset.get_frames_timestamps(), dtype=float)[: len(poses)]

    # In this sensor setup the Ouster metadata states that NMEA leap seconds
    # are added to UDP timestamps. Convert back to Unix/UTC to match SBG/RTS.
    timestamps = raw_timestamps - float(leap_seconds)

    valid = np.isfinite(timestamps)
    if len(timestamps) > 1:
        valid[1:] &= np.diff(timestamps) > 0.0
    poses = poses[valid]
    timestamps = timestamps[valid]

    if len(poses) < 3:
        raise RuntimeError("Too few valid KISS-ICP poses after timestamp validation.")

    write_traj(args.output, timestamps, poses)

    positions = poses[:, :3, 3]
    path_length = float(np.linalg.norm(np.diff(positions, axis=0), axis=1).sum())
    runtime = np.asarray(runtimes_ms, dtype=float)
    metrics = {
        "backend": "KISS-ICP Python",
        "ros_used": False,
        "rosbag_used": False,
        "scans_processed": int(len(poses)),
        "start_unix_s": float(timestamps[0]),
        "end_unix_s": float(timestamps[-1]),
        "duration_s": float(timestamps[-1] - timestamps[0]),
        "path_length_m": path_length,
        "runtime_ms_mean": float(np.mean(runtime)),
        "runtime_ms_median": float(np.median(runtime)),
        "config": {
            "deskew": bool(config.data.deskew),
            "max_range": float(config.data.max_range),
            "min_range": float(config.data.min_range),
            "voxel_size": float(config.mapping.voxel_size),
            "max_points_per_voxel": int(config.mapping.max_points_per_voxel),
            "fixed_threshold": config.adaptive_threshold.fixed_threshold,
            "initial_threshold": float(config.adaptive_threshold.initial_threshold),
            "min_motion_th": float(config.adaptive_threshold.min_motion_th),
            "max_num_iterations": int(config.registration.max_num_iterations),
            "convergence_criterion": float(config.registration.convergence_criterion),
            "max_num_threads": int(config.registration.max_num_threads),
        },
    }

    if args.metrics_out:
        Path(args.metrics_out).write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    print()
    print(json.dumps(metrics, indent=2))
    print(f"Wrote trajectory: {args.output}")


if __name__ == "__main__":
    main()
