#!/usr/bin/env python3
"""
Dedicated Ouster -> ROS1 bag converter for the 2026-07-15 "rotation" dataset.

Dataset defaults:
  PCAP: OS-1-128_122304001981_1024x10_20260715_110449.pcap
  JSON: OS-1-128_122304001981_1024x10_20260715_110449.json
  OUT : rotation_liosam.bag

Important timing rule for THIS setup:
- Ouster timestamp_mode = TIME_FROM_SYNC_PULSE_IN
- multipurpose_io_mode = INPUT_NMEA_UART
- PPS + NMEA are supplied by the SBG Ellipse-D
- Ouster nmea_leap_seconds = 37

Ouster documentation states that nmea_leap_seconds is ADDED to UDP timestamps.
Therefore, to recover Unix/UTC epoch timestamps, this converter subtracts the
metadata's nmea_leap_seconds value from every LiDAR timestamp.

No PCAP host-time alignment, no manual time offset, and no affine stretching
are used.

The output PointCloud2 layout is compatible with LIO-SAM's Ouster input:
  /points_raw
  frame_id = os_lidar
  x, y, z, intensity, t, reflectivity, ring, noise, range
  t = nanoseconds from the first valid column of the scan
"""

import argparse
import json
import os
import sys

import numpy as np
import rospy
import rosbag
from sensor_msgs.msg import PointCloud2, PointField
from std_msgs.msg import Header

from ouster.sdk.pcap.pcap_scan_source import PcapScanSource
from ouster.sdk import client


DEFAULT_PCAP = "OS-1-128_122304001981_1024x10_20260715_110449.pcap"
DEFAULT_JSON = "OS-1-128_122304001981_1024x10_20260715_110449.json"
DEFAULT_OUT = "rotation_liosam.bag"


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


def build_fields():
    return [
        PointField(name="x", offset=0, datatype=PointField.FLOAT32, count=1),
        PointField(name="y", offset=4, datatype=PointField.FLOAT32, count=1),
        PointField(name="z", offset=8, datatype=PointField.FLOAT32, count=1),
        PointField(name="intensity", offset=16, datatype=PointField.FLOAT32, count=1),
        PointField(name="t", offset=20, datatype=PointField.UINT32, count=1),
        PointField(name="reflectivity", offset=24, datatype=PointField.UINT16, count=1),
        PointField(name="ring", offset=26, datatype=PointField.UINT8, count=1),
        PointField(name="noise", offset=28, datatype=PointField.UINT16, count=1),
        PointField(name="range", offset=32, datatype=PointField.UINT32, count=1),
    ]


def scan_to_pointcloud2_bytes(scan, xyz_lut, height, width):
    point_step = 48
    buf = np.zeros((height, width, point_step), dtype=np.uint8)

    xyz = xyz_lut(scan).astype(np.float32)

    range_field = scan.field(client.ChanField.RANGE).astype(np.uint32)
    signal_field = scan.field(client.ChanField.SIGNAL).astype(np.float32)
    reflectivity_field = scan.field(client.ChanField.REFLECTIVITY).astype(np.uint16)
    near_ir_field = scan.field(client.ChanField.NEAR_IR).astype(np.uint16)

    col_ts = scan.timestamp.astype(np.uint64)
    valid_idx = np.flatnonzero(col_ts > 0)

    if valid_idx.size == 0:
        return None, None

    first_idx = int(valid_idx[0])
    first_raw_ts_ns = int(col_ts[first_idx])

    # Relative point/column time: constant epoch/leap offset cancels here.
    rel_ts = np.zeros(width, dtype=np.uint64)
    valid_mask = col_ts > 0
    rel_ts[valid_mask] = col_ts[valid_mask] - np.uint64(first_raw_ts_ns)

    # One 10-Hz scan is ~100 ms, safely inside uint32 nanoseconds.
    if rel_ts.max(initial=0) > np.iinfo(np.uint32).max:
        raise RuntimeError("Per-scan relative timestamp does not fit uint32.")

    rel_ts_u32 = rel_ts.astype(np.uint32)
    rel_ts_full = np.broadcast_to(rel_ts_u32, (height, width))

    ring_idx = np.arange(height, dtype=np.uint8).reshape(height, 1)
    ring_full = np.broadcast_to(ring_idx, (height, width))

    f32 = buf.view(dtype=np.float32).reshape(height, width, point_step // 4)
    u32 = buf.view(dtype=np.uint32).reshape(height, width, point_step // 4)
    u16 = buf.view(dtype=np.uint16).reshape(height, width, point_step // 2)
    u8 = buf

    f32[:, :, 0] = xyz[:, :, 0]
    f32[:, :, 1] = xyz[:, :, 1]
    f32[:, :, 2] = xyz[:, :, 2]
    f32[:, :, 4] = signal_field
    u32[:, :, 5] = rel_ts_full
    u16[:, :, 12] = reflectivity_field
    u8[:, :, 26] = ring_full
    u16[:, :, 14] = near_ir_field
    u32[:, :, 8] = range_field

    return buf.tobytes(), first_raw_ts_ns


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pcap", default=DEFAULT_PCAP)
    ap.add_argument("--metadata", default=DEFAULT_JSON)
    ap.add_argument("--output", default=DEFAULT_OUT)
    ap.add_argument("--topic", default="/points_raw")
    ap.add_argument("--frame-id", default="os_lidar")
    args = ap.parse_args()

    for path in (args.pcap, args.metadata):
        if not os.path.exists(path):
            print(f"ERROR: file not found: {path}")
            sys.exit(1)

    with open(args.metadata, "r") as f:
        metadata_json = json.load(f)

    timestamp_mode = find_key_recursive(metadata_json, "timestamp_mode")
    multipurpose_io_mode = find_key_recursive(metadata_json, "multipurpose_io_mode")
    nmea_leap_seconds = find_key_recursive(metadata_json, "nmea_leap_seconds")

    print("Ouster timing configuration:")
    print("  timestamp_mode       =", timestamp_mode)
    print("  multipurpose_io_mode =", multipurpose_io_mode)
    print("  nmea_leap_seconds    =", nmea_leap_seconds)

    if timestamp_mode != "TIME_FROM_SYNC_PULSE_IN":
        raise RuntimeError(
            "This dedicated converter expects TIME_FROM_SYNC_PULSE_IN."
        )

    if multipurpose_io_mode != "INPUT_NMEA_UART":
        raise RuntimeError(
            "This dedicated converter expects INPUT_NMEA_UART."
        )

    if nmea_leap_seconds is None:
        raise RuntimeError("nmea_leap_seconds not found in metadata.")

    leap_ns = int(nmea_leap_seconds) * 1_000_000_000

    with open(args.metadata) as f:
        info = client.SensorInfo(f.read())

    height = info.format.pixels_per_column
    width = info.format.columns_per_frame

    if height != 128 or width != 1024:
        print(
            f"WARNING: metadata reports {height}x{width}; "
            "expected OS1-128 1024x10 data."
        )

    xyz_lut = client.XYZLut(info)
    source = PcapScanSource(args.pcap, meta=(args.metadata,))
    fields = build_fields()

    bag = rosbag.Bag(args.output, "w")

    count = 0
    first_corrected_ns = None
    last_corrected_ns = None
    previous_corrected_ns = None

    try:
        for scans in source:
            scan = scans[0]
            if scan is None:
                continue

            data_bytes, raw_scan_ts_ns = scan_to_pointcloud2_bytes(
                scan, xyz_lut, height, width
            )
            if data_bytes is None:
                continue

            # Ouster nmea_leap_seconds is ADDED by the sensor.
            # Subtract it to obtain Unix/UTC epoch time.
            corrected_ts_ns = int(raw_scan_ts_ns) - leap_ns

            if previous_corrected_ns is not None and corrected_ts_ns <= previous_corrected_ns:
                raise RuntimeError(
                    "Non-monotonic corrected LiDAR timestamps detected."
                )
            previous_corrected_ns = corrected_ts_ns

            if first_corrected_ns is None:
                first_corrected_ns = corrected_ts_ns
            last_corrected_ns = corrected_ts_ns

            msg = PointCloud2()
            msg.header = Header()
            msg.header.frame_id = args.frame_id
            msg.header.stamp = rospy.Time(
                secs=corrected_ts_ns // 1_000_000_000,
                nsecs=corrected_ts_ns % 1_000_000_000,
            )

            msg.height = height
            msg.width = width
            msg.fields = fields
            msg.is_bigendian = False
            msg.point_step = 48
            msg.row_step = 48 * width

            # LIO-SAM explicitly expects a dense cloud.
            msg.is_dense = True
            msg.data = data_bytes

            bag.write(args.topic, msg, t=msg.header.stamp)
            count += 1

            if count % 50 == 0:
                print(f"Processed {count} scans...")

    finally:
        bag.close()

    if count == 0:
        raise RuntimeError("No LiDAR scans were written.")

    duration = (last_corrected_ns - first_corrected_ns) / 1e9

    print()
    print("Done.")
    print(f"Scans written : {count}")
    print(f"Topic         : {args.topic}")
    print(f"Frame         : {args.frame_id}")
    print(f"Leap correction: -{int(nmea_leap_seconds)}.000000000 s")
    print(f"Start         : {first_corrected_ns / 1e9:.9f}")
    print(f"End           : {last_corrected_ns / 1e9:.9f}")
    print(f"Duration      : {duration:.9f} s")
    print(f"Output        : {args.output}")


if __name__ == "__main__":
    main()
