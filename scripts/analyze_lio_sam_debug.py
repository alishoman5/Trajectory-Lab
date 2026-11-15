#!/usr/bin/env python3
"""Summarize Trajectory Lab's LIO-SAM debug CSV files around failure onset."""

import argparse
import csv
import math
from pathlib import Path


def load_csv(path):
    with Path(path).open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return rows


def f(row, key, default=float("nan")):
    try:
        return float(row.get(key, default))
    except Exception:
        return default


def i(row, key, default=0):
    try:
        return int(float(row.get(key, default)))
    except Exception:
        return default


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("debug_dir")
    ap.add_argument("--jump-m", type=float, default=2.0, help="Flag scan-to-scan pose jumps above this distance")
    ap.add_argument("--context", type=int, default=8)
    args = ap.parse_args()

    root = Path(args.debug_dir).expanduser().resolve()
    map_path = root / "lio_sam_map_debug.csv"
    deskew_path = root / "lio_sam_deskew_debug.csv"
    loop_path = root / "lio_sam_loop_debug.csv"
    if not map_path.is_file():
        raise SystemExit(f"Missing {map_path}")

    rows = load_csv(map_path)
    if len(rows) < 2:
        raise SystemExit("Map debug log has too few rows")

    jumps = []
    for idx in range(1, len(rows)):
        a, b = rows[idx-1], rows[idx]
        dx = f(b,"x")-f(a,"x"); dy=f(b,"y")-f(a,"y"); dz=f(b,"z")-f(a,"z")
        step = math.sqrt(dx*dx+dy*dy+dz*dz)
        rows[idx]["_step_m"] = step
        bad = (
            step > args.jump_m or
            i(b,"lm_converged") == 0 or
            i(b,"is_degenerate") == 1 or
            i(b,"total_corr") < 50 or
            i(b,"imu_available") == 0
        )
        if bad:
            jumps.append(idx)

    max_idx = max(range(1,len(rows)), key=lambda k: float(rows[k].get("_step_m",0.0)))
    first_jump = next((k for k in range(1,len(rows)) if float(rows[k].get("_step_m",0.0)) > args.jump_m), None)
    focus = first_jump if first_jump is not None else max_idx
    t0 = f(rows[focus], "time")

    print("LIO-SAM DEBUG SUMMARY")
    print("=====================")
    print(f"Scans logged: {len(rows)}")
    print(f"Largest scan-to-scan pose step: {float(rows[max_idx].get('_step_m',0.0)):.3f} m at t={f(rows[max_idx],'time'):.6f}")
    if first_jump is not None:
        print(f"First step > {args.jump_m:.2f} m: {float(rows[first_jump].get('_step_m',0.0)):.3f} m at t={t0:.6f}")
    else:
        print(f"No scan-to-scan step exceeded {args.jump_m:.2f} m; showing largest step instead.")

    print("\nContext around failure onset:")
    print("idx,time,step_m,corner,surf,cornerCorr,surfCorr,totalCorr,degenerate,converged,iters,keyframes,z,imu,odom")
    lo=max(0,focus-args.context); hi=min(len(rows),focus+args.context+1)
    for k in range(lo,hi):
        r=rows[k]
        print(",".join([
            str(k), f"{f(r,'time'):.6f}", f"{float(r.get('_step_m',0.0)):.3f}",
            str(i(r,'corner_scan')), str(i(r,'surf_scan')), str(i(r,'corner_corr')), str(i(r,'surf_corr')),
            str(i(r,'total_corr')), str(i(r,'is_degenerate')), str(i(r,'lm_converged')), str(i(r,'lm_iterations')),
            str(i(r,'keyframes')), f"{f(r,'z'):.3f}", str(i(r,'imu_available')), str(i(r,'odom_available'))
        ]))

    if deskew_path.is_file():
        drows=load_csv(deskew_path)
        nearby=[r for r in drows if abs(f(r,"scan_start")-t0)<=2.0]
        failed=[r for r in nearby if i(r,"deskew_ready")==0 or i(r,"imu_covers_scan")==0 or i(r,"imu_available")==0]
        print(f"\nDeskew rows within ±2 s: {len(nearby)}; problematic: {len(failed)}")
        for r in failed[:10]:
            print(f"  t={f(r,'scan_start'):.6f} ready={i(r,'deskew_ready')} imu_cover={i(r,'imu_covers_scan')} imu_available={i(r,'imu_available')} imu_samples={i(r,'imu_samples')} duration={f(r,'scan_duration'):.4f}s")
    else:
        print("\nNo deskew log found.")

    if loop_path.is_file():
        lrows=load_csv(loop_path)
        nearby=[r for r in lrows if abs(f(r,"time")-t0)<=10.0]
        print(f"\nAccepted loop closures within ±10 s: {len(nearby)}")
        for r in nearby:
            print(f"  t={f(r,'time'):.6f} key {i(r,'current_key')} -> {i(r,'previous_key')} fitness={f(r,'fitness'):.6f}")
    else:
        print("\nNo loop log found.")

    deg=sum(i(r,"is_degenerate")==1 for r in rows)
    nonconv=sum(i(r,"lm_converged")==0 for r in rows)
    lowcorr=sum(i(r,"total_corr")<50 for r in rows)
    print("\nWhole-run counts:")
    print(f"  degenerate scans: {deg}")
    print(f"  non-converged LM scans: {nonconv}")
    print(f"  scans with <50 correspondences: {lowcorr}")


if __name__ == "__main__":
    main()
