#!/usr/bin/env python3
"""Post-run diagnostic analysis for Trajectory Lab.

Adds presentation-oriented results on top of the Trajectopy evaluation:
- overall winner (from Trajectopy summary metrics)
- moving-only speed sensitivity for every algorithm
- 5 m relative position drift by speed bin
- worst 5 m trajectory segments per algorithm
- cross-algorithm plots and automatic findings
- dataset leaderboard across saved runs

The speed analysis uses RTS velocity when available and removes stationary
start/end periods. Estimate positions are rigidly aligned (SE3, no scale) to
RTS positions interpolated at the estimate timestamps.
"""

import argparse
import csv
import json
import math
import re
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


MOVING_THRESHOLD = 0.30
LOW_MAX = 1.20
MEDIUM_MAX = 1.60
SEGMENT_LENGTH_M = 5.0
RPE_DISTANCE_M = 5.0
MIN_BIN_POSES = 3

SPEED_BINS = [
    ("low", "Low (0.3–1.2 m/s)", MOVING_THRESHOLD, LOW_MAX),
    ("medium", "Medium (1.2–1.6 m/s)", LOW_MAX, MEDIUM_MAX),
    ("high", "High (>1.6 m/s)", MEDIUM_MAX, float("inf")),
]


def json_safe(x):
    if isinstance(x, dict):
        return {str(k): json_safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [json_safe(v) for v in x]
    if isinstance(x, np.ndarray):
        return x.tolist()
    if isinstance(x, (np.floating, np.integer)):
        return x.item()
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return None
    return x


def read_traj(path):
    """Read the project .traj format: t,l,px,py,pz,vx,vy,vz."""
    t, length, pos, vel = [], [], [], []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = re.split(r"[,\s]+", line)
            if len(parts) < 5:
                continue
            try:
                tv = float(parts[0])
                lv = float(parts[1]) if len(parts) > 1 else float("nan")
                p = [float(parts[2]), float(parts[3]), float(parts[4])]
                if len(parts) >= 8:
                    v = [float(parts[5]), float(parts[6]), float(parts[7])]
                else:
                    v = [float("nan")] * 3
            except ValueError:
                continue
            t.append(tv); length.append(lv); pos.append(p); vel.append(v)
    if len(t) < 2:
        raise RuntimeError(f"Trajectory has too few poses: {path}")
    t = np.asarray(t, dtype=float)
    length = np.asarray(length, dtype=float)
    pos = np.asarray(pos, dtype=float)
    vel = np.asarray(vel, dtype=float)
    order = np.argsort(t)
    t, length, pos, vel = t[order], length[order], pos[order], vel[order]
    unique, idx = np.unique(t, return_index=True)
    return {
        "t": unique,
        "length": length[idx],
        "pos": pos[idx],
        "vel": vel[idx],
    }


def ensure_reference_length(ref):
    l = ref["length"].copy()
    if len(l) != len(ref["t"]) or not np.all(np.isfinite(l)) or np.any(np.diff(l) < -1e-6):
        step = np.linalg.norm(np.diff(ref["pos"], axis=0), axis=1)
        l = np.concatenate([[0.0], np.cumsum(step)])
    ref["length"] = l


def ensure_reference_speed(ref):
    vel = ref["vel"]
    if vel.shape == ref["pos"].shape and np.all(np.isfinite(vel)):
        speed = np.linalg.norm(vel, axis=1)
    else:
        t = ref["t"]
        p = ref["pos"]
        speed = np.sqrt(sum(np.gradient(p[:, k], t) ** 2 for k in range(3)))
    # Small median filter without pandas.
    out = np.empty_like(speed)
    radius = 2
    for i in range(len(speed)):
        out[i] = np.median(speed[max(0, i-radius):min(len(speed), i+radius+1)])
    ref["speed"] = out


def interp_columns(query_t, source_t, values):
    values = np.asarray(values)
    if values.ndim == 1:
        return np.interp(query_t, source_t, values)
    return np.column_stack([
        np.interp(query_t, source_t, values[:, k]) for k in range(values.shape[1])
    ])


def rigid_align(src, dst):
    src_c = np.mean(src, axis=0)
    dst_c = np.mean(dst, axis=0)
    H = (src - src_c).T @ (dst - dst_c)
    U, _, Vt = np.linalg.svd(H)
    R = Vt.T @ U.T
    if np.linalg.det(R) < 0:
        Vt[-1, :] *= -1
        R = Vt.T @ U.T
    trans = dst_c - R @ src_c
    aligned = (R @ src.T).T + trans
    return aligned, R, trans


def stats(x):
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return {"count": 0, "mean": None, "rmse": None, "median": None, "std": None, "max": None}
    return {
        "count": int(len(x)),
        "mean": float(np.mean(x)),
        "rmse": float(np.sqrt(np.mean(x*x))),
        "median": float(np.median(x)),
        "std": float(np.std(x)),
        "max": float(np.max(x)),
    }


def classify_speed(v):
    if v < MOVING_THRESHOLD:
        return None
    if v < LOW_MAX:
        return "low"
    if v <= MEDIUM_MAX:
        return "medium"
    return "high"


def analyze_algorithm(ref, est_path, alg):
    est = read_traj(est_path)
    mask = (est["t"] >= ref["t"][0]) & (est["t"] <= ref["t"][-1])
    et = est["t"][mask]
    ep = est["pos"][mask]
    if len(et) < 3:
        raise RuntimeError(f"Only {len(et)} poses overlap RTS for {alg['name']}")

    gp = interp_columns(et, ref["t"], ref["pos"])
    gs = np.interp(et, ref["t"], ref["speed"])
    gl = np.interp(et, ref["t"], ref["length"])

    aligned, R, trans = rigid_align(ep, gp)
    error = np.linalg.norm(aligned - gp, axis=1)

    moving_candidates = np.where(gs >= MOVING_THRESHOLD)[0]
    if len(moving_candidates):
        first, last = int(moving_candidates[0]), int(moving_candidates[-1])
    else:
        first, last = 0, len(et) - 1

    interval_mask = np.zeros(len(et), dtype=bool)
    interval_mask[first:last+1] = True
    moving_mask = interval_mask & (gs >= MOVING_THRESHOLD)
    move_idx = np.where(moving_mask)[0]

    distance0 = gl[first]
    distance_rel = gl - distance0

    speed_bins = {}
    for key, label, lo, hi in SPEED_BINS:
        if math.isinf(hi):
            bm = moving_mask & (gs > lo)
        elif key == "low":
            bm = moving_mask & (gs >= lo) & (gs < hi)
        else:
            bm = moving_mask & (gs >= lo) & (gs <= hi)
        st = stats(error[bm])
        st.update({
            "label": label,
            "mean_speed_m_s": float(np.mean(gs[bm])) if np.any(bm) else None,
        })
        speed_bins[key] = st

    # 5 m translational relative-position diagnostic.
    rpe_samples = {k: [] for k, *_ in SPEED_BINS}
    moving_indices = np.where(interval_mask)[0]
    for i in moving_indices:
        if gs[i] < MOVING_THRESHOLD:
            continue
        target = gl[i] + RPE_DISTANCE_M
        j = int(np.searchsorted(gl, target, side="left"))
        if j >= len(gl) or not interval_mask[j]:
            continue
        baseline = float(gl[j] - gl[i])
        if baseline < 4.5:
            continue
        mean_speed = float(np.mean(gs[i:j+1]))
        key = classify_speed(mean_speed)
        if key is None:
            continue
        gt_delta = gp[j] - gp[i]
        est_delta = aligned[j] - aligned[i]
        rpe_m = float(np.linalg.norm(est_delta - gt_delta))
        rpe_samples[key].append((rpe_m, 100.0 * rpe_m / baseline, mean_speed))

    rpe_bins = {}
    for key, label, _, _ in SPEED_BINS:
        vals = rpe_samples[key]
        metres = [v[0] for v in vals]
        pct = [v[1] for v in vals]
        rpe_bins[key] = {
            "label": label,
            "windows": len(vals),
            "mean_m": float(np.mean(metres)) if vals else None,
            "rmse_m": float(np.sqrt(np.mean(np.square(metres)))) if vals else None,
            "median_m": float(np.median(metres)) if vals else None,
            "max_m": float(np.max(metres)) if vals else None,
            "mean_percent": float(np.mean(pct)) if vals else None,
            "median_percent": float(np.median(pct)) if vals else None,
            "max_percent": float(np.max(pct)) if vals else None,
        }

    # Worst 5 m bins during the actual moving interval.
    worst = []
    if len(move_idx):
        bins = np.floor(np.maximum(distance_rel, 0.0) / SEGMENT_LENGTH_M).astype(int)
        for b in np.unique(bins[moving_mask]):
            bm = moving_mask & (bins == b)
            if np.count_nonzero(bm) < 1:
                continue
            e = error[bm]
            worst.append({
                "segment": int(b),
                "distance_start_m": float(np.min(distance_rel[bm])),
                "distance_end_m": float(np.max(distance_rel[bm])),
                "poses": int(np.count_nonzero(bm)),
                "mean_ate_m": float(np.mean(e)),
                "max_ate_m": float(np.max(e)),
                "mean_speed_m_s": float(np.mean(gs[bm])),
            })
        worst.sort(key=lambda r: r["mean_ate_m"], reverse=True)

    if np.count_nonzero(moving_mask) >= 3:
        corr = float(np.corrcoef(gs[moving_mask], error[moving_mask])[0, 1])
    else:
        corr = None

    return {
        "id": alg["id"],
        "name": alg["name"],
        "source_traj": str(est_path),
        "overlap_poses": int(len(et)),
        "moving_poses": int(np.count_nonzero(moving_mask)),
        "moving_start_s": float(et[first] - et[0]),
        "moving_end_s": float(et[last] - et[0]),
        "moving_distance_m": float(max(0.0, gl[last] - gl[first])),
        "speed_ate_correlation": corr,
        "moving_ate": stats(error[moving_mask]),
        "speed_bins": speed_bins,
        "rpe_5m_bins": rpe_bins,
        "worst_segments": worst[:5],
        "alignment_rotation": R.tolist(),
        "alignment_translation": trans.tolist(),
        # Arrays are kept only for plotting, removed before JSON serialization.
        "_plot": {
            "distance": distance_rel[moving_mask],
            "error": error[moving_mask],
            "speed": gs[moving_mask],
        },
    }


def metric_mean(m):
    ate = m.get("ate", {}) or {}
    v = ate.get("pos_mean_m", m.get("ate_mean_m", m.get("mean_error_m")))
    return float(v) if v is not None else float("inf")


def metric_rms(m):
    ate = m.get("ate", {}) or {}
    v = ate.get("pos_rms_m", m.get("rms_3d_m", m.get("ate_rmse_m")))
    return float(v) if v is not None else float("inf")


def choose_best(analyses, bin_key=None, rpe=False):
    candidates = []
    for a in analyses:
        if rpe:
            b = a["rpe_5m_bins"].get(bin_key, {})
            value = b.get("mean_percent")
            count = b.get("windows", 0)
        elif bin_key:
            b = a["speed_bins"].get(bin_key, {})
            value = b.get("mean")
            count = b.get("count", 0)
        else:
            value = a["moving_ate"].get("mean")
            count = a.get("moving_poses", 0)
        if value is not None and count >= MIN_BIN_POSES:
            candidates.append((float(value), a["id"], a["name"], int(count)))
    if not candidates:
        return None
    value, aid, name, count = min(candidates)
    return {"id": aid, "name": name, "value": value, "samples": count}


def make_findings(dataset_name, overall_metrics, analyses, best_by_speed, best_rpe):
    findings = []
    if overall_metrics:
        ranked = sorted(overall_metrics, key=metric_mean)
        best = ranked[0]
        findings.append(
            f"Best overall on {dataset_name}: {best.get('name','')} "
            f"(Trajectopy ATE mean {metric_mean(best):.3f} m, RMS {metric_rms(best):.3f} m)."
        )
    for key, label, _, _ in SPEED_BINS:
        b = best_by_speed.get(key)
        if b:
            findings.append(f"Best {label.lower()}: {b['name']} (mean ATE {b['value']:.3f} m).")
    # Speed sensitivity: difference high-low among algorithms having both bins.
    sensitivities = []
    for a in analyses:
        low = a["speed_bins"]["low"].get("mean")
        high = a["speed_bins"]["high"].get("mean")
        if low is not None and high is not None:
            sensitivities.append((float(high - low), a))
    if sensitivities:
        delta, a = max(sensitivities, key=lambda x: x[0])
        findings.append(
            f"Largest high-vs-low speed ATE increase: {a['name']} ({delta:+.3f} m)."
        )
    # Worst observed 5m segment.
    worst_all = []
    for a in analyses:
        if a["worst_segments"]:
            w = a["worst_segments"][0]
            worst_all.append((w["mean_ate_m"], a, w))
    if worst_all:
        _, a, w = max(worst_all, key=lambda x: x[0])
        findings.append(
            f"Largest mean error segment: {a['name']} at {w['distance_start_m']:.1f}–"
            f"{w['distance_end_m']:.1f} m (mean ATE {w['mean_ate_m']:.3f} m)."
        )
    return findings


def plot_results(out, analyses):
    paths = {}
    # 1. ATE vs travelled distance.
    fig, ax = plt.subplots(figsize=(12, 6))
    for a in analyses:
        p = a["_plot"]
        if len(p["distance"]):
            ax.plot(p["distance"], p["error"], linewidth=1.5, label=a["name"])
    ax.set_xlabel("RTS travelled distance from movement start [m]")
    ax.set_ylabel("Position error [m]")
    ax.set_title("Algorithm error along the moving trajectory")
    ax.grid(True); ax.legend(); fig.tight_layout()
    path = out / "diagnostic_ate_vs_distance.png"; fig.savefig(path, dpi=200); plt.close(fig); paths["ate_distance"] = str(path)

    # 2. Grouped ATE mean by speed.
    fig, ax = plt.subplots(figsize=(12, 6))
    x = np.arange(3); n = max(1, len(analyses)); width = min(0.24, 0.72/n)
    offsets = (np.arange(n) - (n-1)/2) * width
    for i, a in enumerate(analyses):
        vals = [a["speed_bins"][k].get("mean") for k, *_ in SPEED_BINS]
        ax.bar(x + offsets[i], [np.nan if v is None else v for v in vals], width=width, label=a["name"])
    ax.set_xticks(x); ax.set_xticklabels([label for _, label, _, _ in SPEED_BINS])
    ax.set_ylabel("Mean ATE [m]"); ax.set_title("Speed sensitivity: mean ATE by algorithm")
    ax.grid(True, axis="y"); ax.legend(); fig.tight_layout()
    path = out / "diagnostic_speed_ate.png"; fig.savefig(path, dpi=200); plt.close(fig); paths["speed_ate"] = str(path)

    # 3. 5m RPE by speed.
    fig, ax = plt.subplots(figsize=(12, 6))
    for i, a in enumerate(analyses):
        vals = [a["rpe_5m_bins"][k].get("mean_percent") for k, *_ in SPEED_BINS]
        ax.bar(x + offsets[i], [np.nan if v is None else v for v in vals], width=width, label=a["name"])
    ax.set_xticks(x); ax.set_xticklabels([label for _, label, _, _ in SPEED_BINS])
    ax.set_ylabel("5 m relative position error [%]"); ax.set_title("Local drift by platform speed")
    ax.grid(True, axis="y"); ax.legend(); fig.tight_layout()
    path = out / "diagnostic_speed_rpe.png"; fig.savefig(path, dpi=200); plt.close(fig); paths["speed_rpe"] = str(path)

    # 4. Speed vs ATE scatter.
    fig, ax = plt.subplots(figsize=(10, 7))
    for a in analyses:
        p = a["_plot"]
        if len(p["speed"]):
            ax.scatter(p["speed"], p["error"], s=18, alpha=0.55, label=f"{a['name']} (r={a['speed_ate_correlation']:+.2f})" if a['speed_ate_correlation'] is not None else a['name'])
    ax.axvline(LOW_MAX, linestyle="--", linewidth=1); ax.axvline(MEDIUM_MAX, linestyle="--", linewidth=1)
    ax.set_xlabel("RTS platform speed [m/s]"); ax.set_ylabel("Position error [m]")
    ax.set_title("ATE vs platform speed"); ax.grid(True); ax.legend(); fig.tight_layout()
    path = out / "diagnostic_ate_vs_speed.png"; fig.savefig(path, dpi=200); plt.close(fig); paths["ate_speed"] = str(path)

    # 5. Segment heatmap, common 5m bins.
    max_seg = max([max([w["segment"] for w in a["worst_segments"]], default=0) for a in analyses] + [0])
    # Reconstruct all segment means from plot arrays for a complete heatmap.
    matrices = []
    max_dist = max([float(np.max(a["_plot"]["distance"])) if len(a["_plot"]["distance"]) else 0.0 for a in analyses] + [0.0])
    nbins = max(1, int(math.ceil(max_dist / SEGMENT_LENGTH_M)))
    for a in analyses:
        d, e = a["_plot"]["distance"], a["_plot"]["error"]
        row = []
        for b in range(nbins):
            m = (d >= b*SEGMENT_LENGTH_M) & (d < (b+1)*SEGMENT_LENGTH_M)
            row.append(float(np.mean(e[m])) if np.any(m) else np.nan)
        matrices.append(row)
    mat = np.asarray(matrices, dtype=float)
    fig, ax = plt.subplots(figsize=(max(10, nbins*0.7), max(4, len(analyses)*1.0)))
    im = ax.imshow(mat, aspect="auto", interpolation="nearest")
    ax.set_yticks(np.arange(len(analyses))); ax.set_yticklabels([a["name"] for a in analyses])
    ax.set_xticks(np.arange(nbins)); ax.set_xticklabels([f"{b*5}–{(b+1)*5}" for b in range(nbins)], rotation=45, ha="right")
    ax.set_xlabel("RTS distance segment [m]"); ax.set_title("Mean ATE by 5 m segment")
    cb = fig.colorbar(im, ax=ax); cb.set_label("Mean ATE [m]")
    fig.tight_layout(); path = out / "diagnostic_segment_heatmap.png"; fig.savefig(path, dpi=200); plt.close(fig); paths["segment_heatmap"] = str(path)
    return paths


def write_csvs(out, analyses):
    speed_csv = out / "diagnostic_speed_summary.csv"
    with speed_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Algorithm", "Speed bin", "Poses", "Mean speed [m/s]", "Mean ATE [m]", "ATE RMSE [m]", "Median ATE [m]", "Max ATE [m]", "Speed/ATE correlation"])
        for a in analyses:
            for key, label, _, _ in SPEED_BINS:
                b = a["speed_bins"][key]
                w.writerow([a["name"], label, b["count"], b["mean_speed_m_s"], b["mean"], b["rmse"], b["median"], b["max"], a["speed_ate_correlation"]])

    seg_csv = out / "diagnostic_worst_segments.csv"
    with seg_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Algorithm", "Rank", "Distance start [m]", "Distance end [m]", "Poses", "Mean ATE [m]", "Max ATE [m]", "Mean speed [m/s]"])
        for a in analyses:
            for rank, s in enumerate(a["worst_segments"], 1):
                w.writerow([a["name"], rank, s["distance_start_m"], s["distance_end_m"], s["poses"], s["mean_ate_m"], s["max_ate_m"], s["mean_speed_m_s"]])
    return str(speed_csv), str(seg_csv)


def infer_dataset_name(run_dir):
    meta = run_dir / "run_metadata.json"
    if meta.exists():
        try:
            return json.loads(meta.read_text()).get("dataset_name") or run_dir.name
        except Exception:
            pass
    return re.sub(r"_\d{8}_\d{6}$", "", run_dir.name)


def update_history(root_out):
    rows = []
    for mf in root_out.glob("*/comparison/summary_metrics.json"):
        run_dir = mf.parent.parent
        try:
            metrics = json.loads(mf.read_text())
            if not metrics:
                continue
            best = min(metrics, key=metric_mean)
            perf_file = mf.parent / "performance_analysis.json"
            best_speed = {"low": None, "medium": None, "high": None}
            if perf_file.exists():
                try:
                    p = json.loads(perf_file.read_text())
                    for k in best_speed:
                        b = p.get("best_by_speed", {}).get(k)
                        best_speed[k] = b.get("name") if b else None
                except Exception:
                    pass
            rows.append({
                "dataset": infer_dataset_name(run_dir),
                "run": run_dir.name,
                "best_overall": best.get("name", ""),
                "ate_mean_m": metric_mean(best),
                "ate_rms_m": metric_rms(best),
                "algorithms_tested": len(metrics),
                "best_low_speed": best_speed["low"],
                "best_medium_speed": best_speed["medium"],
                "best_high_speed": best_speed["high"],
                "run_dir": str(run_dir),
            })
        except Exception:
            continue
    rows.sort(key=lambda r: (r["dataset"], r["run"]), reverse=False)
    j = root_out / "dataset_leaderboard.json"
    j.write_text(json.dumps(json_safe(rows), indent=2), encoding="utf-8")
    c = root_out / "dataset_leaderboard.csv"
    with c.open("w", newline="", encoding="utf-8") as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader(); w.writerows(rows)
    return str(j), str(c)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--metrics", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--dataset-name", required=True)
    ap.add_argument("--output-root", required=True)
    args = ap.parse_args()

    out = Path(args.out_dir).resolve(); out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(Path(args.manifest).read_text())
    overall_metrics = json.loads(Path(args.metrics).read_text())
    ref = read_traj(manifest["rts"]); ensure_reference_length(ref); ensure_reference_speed(ref)

    analyses = []
    for alg in manifest.get("estimates", []):
        try:
            analyses.append(analyze_algorithm(ref, alg["traj"], alg))
        except Exception as e:
            print(f"WARNING: diagnostic analysis failed for {alg.get('name')}: {e}")

    if not analyses:
        raise RuntimeError("No algorithm could be analyzed for diagnostics.")

    best_by_speed = {key: choose_best(analyses, key) for key, *_ in SPEED_BINS}
    best_rpe = {key: choose_best(analyses, key, rpe=True) for key, *_ in SPEED_BINS}
    best_moving = choose_best(analyses)
    findings = make_findings(args.dataset_name, overall_metrics, analyses, best_by_speed, best_rpe)
    plots = plot_results(out, analyses)
    speed_csv, segments_csv = write_csvs(out, analyses)

    serial_analyses = []
    for a in analyses:
        b = dict(a); b.pop("_plot", None); serial_analyses.append(b)

    result = {
        "dataset_name": args.dataset_name,
        "settings": {
            "moving_threshold_m_s": MOVING_THRESHOLD,
            "low_max_m_s": LOW_MAX,
            "medium_max_m_s": MEDIUM_MAX,
            "segment_length_m": SEGMENT_LENGTH_M,
            "rpe_distance_m": RPE_DISTANCE_M,
            "alignment": "Rigid SE(3), no scale; RTS position interpolated at estimate timestamps",
        },
        "best_moving_overall": best_moving,
        "best_by_speed": best_by_speed,
        "best_rpe_by_speed": best_rpe,
        "findings": findings,
        "algorithms": serial_analyses,
        "plots": plots,
        "speed_csv": speed_csv,
        "segments_csv": segments_csv,
    }
    perf_file = out / "performance_analysis.json"
    perf_file.write_text(json.dumps(json_safe(result), indent=2), encoding="utf-8")

    history_json, history_csv = update_history(Path(args.output_root).expanduser().resolve())
    result["history_json"] = history_json; result["history_csv"] = history_csv
    perf_file.write_text(json.dumps(json_safe(result), indent=2), encoding="utf-8")

    print("Performance analysis complete")
    for line in findings:
        print(" - " + line)
    print(f"Saved: {perf_file}")


if __name__ == "__main__":
    main()