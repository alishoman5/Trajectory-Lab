#!/usr/bin/env python3
"""Build a local ENU reference trajectory from SBG ECom GNSS/navigation logs.

Priority:
1. Raw primary GNSS position SBG_ECOM_LOG_GPS1_POS (ID 14), optionally with
   GPS1_VEL (ID 13).
2. Fallback to fused SBG_ECOM_LOG_EKF_NAV (ID 8) if raw GNSS position is not
   available.

The output is the Trajectory Lab .traj format:
  t,l,px,py,pz,vx,vy,vz

Position is expressed in a local ENU frame relative to the first valid sample.
GNSS MSL altitude is converted to ellipsoidal height using the SBG undulation
field before the WGS84 ECEF->ENU conversion.
"""

import argparse
import calendar
import json
import math
import struct
from pathlib import Path

import numpy as np


SYNC1 = 0xFF
SYNC2 = 0x5A
ETX = 0x33

WGS84_A = 6378137.0
WGS84_F = 1.0 / 298.257223563
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)


def _iter_frames(data):
    i = 0
    n = len(data)
    while i + 9 <= n:
        if data[i] != SYNC1 or data[i + 1] != SYNC2:
            i += 1
            continue
        msg_id = data[i + 2]
        msg_class = data[i + 3]
        length = struct.unpack_from("<H", data, i + 4)[0]
        frame_size = 6 + length + 2 + 1
        if i + frame_size > n:
            break
        if data[i + frame_size - 1] != ETX:
            i += 1
            continue
        payload = data[i + 6:i + 6 + length]
        yield msg_id, msg_class, payload
        i += frame_size


def _unix_offset_ns(utc_rows):
    if not utc_rows:
        raise RuntimeError("No SBG UTC messages (ID 2) found; cannot timestamp GNSS reference.")
    offsets = np.asarray(
        [epoch_ns - int(sensor_us) * 1000 for sensor_us, epoch_ns in utc_rows],
        dtype=np.int64,
    )
    return int(np.median(offsets))


def _sensor_us_to_unix(sensor_us, offset_ns):
    return (int(sensor_us) * 1000 + int(offset_ns)) / 1e9


def _geodetic_to_ecef(lat_deg, lon_deg, h_m):
    lat = np.deg2rad(lat_deg)
    lon = np.deg2rad(lon_deg)
    sin_lat = np.sin(lat)
    cos_lat = np.cos(lat)
    sin_lon = np.sin(lon)
    cos_lon = np.cos(lon)
    n = WGS84_A / np.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
    x = (n + h_m) * cos_lat * cos_lon
    y = (n + h_m) * cos_lat * sin_lon
    z = (n * (1.0 - WGS84_E2) + h_m) * sin_lat
    return np.column_stack([x, y, z])


def _ecef_to_local_enu(ecef, lat0_deg, lon0_deg, origin_ecef):
    lat0 = math.radians(float(lat0_deg))
    lon0 = math.radians(float(lon0_deg))
    slat, clat = math.sin(lat0), math.cos(lat0)
    slon, clon = math.sin(lon0), math.cos(lon0)
    r = np.array([
        [-slon,          clon,         0.0],
        [-slat * clon,  -slat * slon, clat],
        [ clat * clon,   clat * slon, slat],
    ])
    return (r @ (ecef - origin_ecef).T).T


def _interp_velocity(query_t, vel_rows):
    if len(vel_rows) < 2:
        return None
    vt = np.asarray([r[0] for r in vel_rows], dtype=float)
    vv = np.asarray([r[1] for r in vel_rows], dtype=float)
    order = np.argsort(vt)
    vt, vv = vt[order], vv[order]
    unique, idx = np.unique(vt, return_index=True)
    vt, vv = unique, vv[idx]
    if len(vt) < 2:
        return None
    out = np.column_stack([
        np.interp(query_t, vt, vv[:, k], left=np.nan, right=np.nan)
        for k in range(3)
    ])
    return out


def _derive_velocity(t, pos):
    if len(t) < 3:
        return np.zeros_like(pos)
    return np.column_stack([np.gradient(pos[:, k], t) for k in range(3)])


def _resample_segments(t, pos, vel, rate_hz=10.0, max_gap_s=1.0):
    if rate_hz <= 0 or len(t) < 2:
        return t, pos, vel

    dt = 1.0 / float(rate_hz)
    breaks = np.where(np.diff(t) > max_gap_s)[0]
    starts = np.concatenate([[0], breaks + 1])
    stops = np.concatenate([breaks + 1, [len(t)]])

    tout, pout, vout = [], [], []
    for s, e in zip(starts, stops):
        if e - s < 2:
            continue
        ts = t[s:e]
        ps = pos[s:e]
        vs = vel[s:e]
        grid = np.arange(ts[0], ts[-1] + 0.25 * dt, dt)
        if len(grid) < 2:
            continue
        pi = np.column_stack([np.interp(grid, ts, ps[:, k]) for k in range(3)])
        vi = np.column_stack([np.interp(grid, ts, vs[:, k]) for k in range(3)])
        tout.append(grid); pout.append(pi); vout.append(vi)

    if not tout:
        return t, pos, vel
    return np.concatenate(tout), np.vstack(pout), np.vstack(vout)


def parse_sbg_reference(path, prefer_raw_gnss=True):
    data = Path(path).expanduser().resolve().read_bytes()
    utc = []
    gps_pos = []
    gps_vel = []
    ekf_nav = []

    for msg_id, msg_class, payload in _iter_frames(data):
        if msg_class != 0:
            continue

        if msg_id == 2 and len(payload) == 21:
            sensor_us = struct.unpack_from("<I", payload, 0)[0]
            year = struct.unpack_from("<H", payload, 6)[0]
            month, day, hour, minute, second = struct.unpack_from("<5B", payload, 8)
            nanosecond = struct.unpack_from("<I", payload, 13)[0]
            if 2000 <= year <= 2100:
                try:
                    epoch_sec = calendar.timegm((year, month, day, hour, minute, second))
                    utc.append((sensor_us, epoch_sec * 1_000_000_000 + int(nanosecond)))
                except (ValueError, OverflowError):
                    pass

        elif msg_id == 14 and len(payload) >= 52:
            sensor_us, status = struct.unpack_from("<II", payload, 0)
            status_code = status & 0x3F
            solution_type = (status >> 6) & 0x3F
            lat = struct.unpack_from("<d", payload, 12)[0]
            lon = struct.unpack_from("<d", payload, 20)[0]
            alt_msl = struct.unpack_from("<d", payload, 28)[0]
            undulation = struct.unpack_from("<f", payload, 36)[0]
            lat_acc, lon_acc, alt_acc = struct.unpack_from("<3f", payload, 40)
            valid = (
                status_code == 0 and solution_type != 0
                and math.isfinite(lat) and math.isfinite(lon)
                and math.isfinite(alt_msl) and -90.0 <= lat <= 90.0
                and -180.0 <= lon <= 180.0
            )
            if valid:
                gps_pos.append({
                    "sensor_us": sensor_us, "lat": lat, "lon": lon,
                    "h": alt_msl + undulation,
                    "lat_acc": float(lat_acc), "lon_acc": float(lon_acc),
                    "alt_acc": float(alt_acc), "solution_type": int(solution_type),
                })

        elif msg_id == 13 and len(payload) >= 44:
            sensor_us, status = struct.unpack_from("<II", payload, 0)
            status_code = status & 0x3F
            solution_type = (status >> 6) & 0x3F
            vn, ve, vd = struct.unpack_from("<3f", payload, 12)
            if status_code == 0 and solution_type != 0 and all(map(math.isfinite, (vn, ve, vd))):
                gps_vel.append((sensor_us, np.array([ve, vn, -vd], dtype=float)))

        elif msg_id == 8 and len(payload) >= 72:
            sensor_us = struct.unpack_from("<I", payload, 0)[0]
            vn, ve, vd = struct.unpack_from("<3f", payload, 4)
            lat = struct.unpack_from("<d", payload, 28)[0]
            lon = struct.unpack_from("<d", payload, 36)[0]
            alt_msl = struct.unpack_from("<d", payload, 44)[0]
            undulation = struct.unpack_from("<f", payload, 52)[0]
            lat_acc, lon_acc, alt_acc = struct.unpack_from("<3f", payload, 56)
            status = struct.unpack_from("<I", payload, 68)[0]
            if (
                math.isfinite(lat) and math.isfinite(lon) and math.isfinite(alt_msl)
                and -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0
                and all(map(math.isfinite, (vn, ve, vd)))
            ):
                ekf_nav.append({
                    "sensor_us": sensor_us, "lat": lat, "lon": lon,
                    "h": alt_msl + undulation,
                    "vel_enu": np.array([ve, vn, -vd], dtype=float),
                    "lat_acc": float(lat_acc), "lon_acc": float(lon_acc),
                    "alt_acc": float(alt_acc), "status": int(status),
                })

    offset_ns = _unix_offset_ns(utc)

    use_raw = prefer_raw_gnss and len(gps_pos) >= 3
    if use_raw:
        rows = sorted(gps_pos, key=lambda r: r["sensor_us"])
        source = "SBG GPS1 raw GNSS"
        t = np.asarray([_sensor_us_to_unix(r["sensor_us"], offset_ns) for r in rows], dtype=float)
        lat = np.asarray([r["lat"] for r in rows], dtype=float)
        lon = np.asarray([r["lon"] for r in rows], dtype=float)
        h = np.asarray([r["h"] for r in rows], dtype=float)
        acc = np.asarray([[r["lat_acc"], r["lon_acc"], r["alt_acc"]] for r in rows], dtype=float)

        vel_rows = [
            (_sensor_us_to_unix(sensor_us, offset_ns), vel)
            for sensor_us, vel in gps_vel
        ]
        vel = _interp_velocity(t, vel_rows)
    elif len(ekf_nav) >= 3:
        rows = sorted(ekf_nav, key=lambda r: r["sensor_us"])
        source = "SBG GNSS/INS EKF_NAV"
        t = np.asarray([_sensor_us_to_unix(r["sensor_us"], offset_ns) for r in rows], dtype=float)
        lat = np.asarray([r["lat"] for r in rows], dtype=float)
        lon = np.asarray([r["lon"] for r in rows], dtype=float)
        h = np.asarray([r["h"] for r in rows], dtype=float)
        vel = np.asarray([r["vel_enu"] for r in rows], dtype=float)
        acc = np.asarray([[r["lat_acc"], r["lon_acc"], r["alt_acc"]] for r in rows], dtype=float)
    else:
        raise RuntimeError(
            "No usable SBG GNSS reference found. Need GPS1_POS (ID 14) or EKF_NAV (ID 8) "
            "messages plus UTC (ID 2) in the SBG binary log."
        )

    order = np.argsort(t)
    t, lat, lon, h, acc = t[order], lat[order], lon[order], h[order], acc[order]
    if vel is not None:
        vel = vel[order]

    unique, idx = np.unique(t, return_index=True)
    t, lat, lon, h, acc = unique, lat[idx], lon[idx], h[idx], acc[idx]
    if vel is not None:
        vel = vel[idx]

    ecef = _geodetic_to_ecef(lat, lon, h)
    pos = _ecef_to_local_enu(ecef, lat[0], lon[0], ecef[0])

    if vel is None or not np.all(np.isfinite(vel)):
        vel = _derive_velocity(t, pos)

    horizontal_sigma = np.sqrt(acc[:, 0] ** 2 + acc[:, 1] ** 2)
    meta = {
        "source": source,
        "raw_samples": int(len(t)),
        "start_unix_s": float(t[0]),
        "end_unix_s": float(t[-1]),
        "duration_s": float(t[-1] - t[0]),
        "origin": {
            "latitude_deg": float(lat[0]),
            "longitude_deg": float(lon[0]),
            "ellipsoidal_height_m": float(h[0]),
        },
        "accuracy_1sigma_m": {
            "horizontal_median": float(np.nanmedian(horizontal_sigma)),
            "horizontal_max": float(np.nanmax(horizontal_sigma)),
            "vertical_median": float(np.nanmedian(acc[:, 2])),
            "vertical_max": float(np.nanmax(acc[:, 2])),
        },
        "note": (
            "GNSS/INS fallback reference is not equivalent to RTS ground truth. "
            "Interpret ATE/RPE relative to this reference accuracy."
        ),
    }
    return t, pos, vel, meta


def write_traj(path, t, pos, vel, name):
    step = np.linalg.norm(np.diff(pos, axis=0), axis=1)
    length = np.concatenate([[0.0], np.cumsum(step)])
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


def convert_sbg_to_reference(sbg_path, output_path, metadata_path=None, rate_hz=10.0):
    t, pos, vel, meta = parse_sbg_reference(sbg_path)
    t, pos, vel = _resample_segments(t, pos, vel, rate_hz=rate_hz)
    meta["output_samples"] = int(len(t))
    meta["resample_rate_hz"] = float(rate_hz)

    name = "SBG_GNSS_reference" if meta["source"] == "SBG GPS1 raw GNSS" else "SBG_GNSS_INS_reference"
    write_traj(output_path, t, pos, vel, name)

    if metadata_path:
        Path(metadata_path).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sbg", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--metadata-out", default="")
    ap.add_argument("--rate-hz", type=float, default=10.0)
    args = ap.parse_args()

    meta = convert_sbg_to_reference(
        args.sbg, args.output,
        metadata_path=args.metadata_out or None,
        rate_hz=args.rate_hz,
    )
    print(json.dumps(meta, indent=2))
    print(f"Wrote reference trajectory: {args.output}")


if __name__ == "__main__":
    main()
