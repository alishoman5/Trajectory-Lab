#!/usr/bin/env python3
import argparse
import math
import rosbag


def main():
    ap = argparse.ArgumentParser(description="Export nav_msgs/Odometry from ROS1 bag to Trajectopy .traj")
    ap.add_argument("bag")
    ap.add_argument("--topic", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--name", default="estimate")
    args = ap.parse_args()

    times = []
    pos = []

    with rosbag.Bag(args.bag, "r") as bag:
        for _, msg, _ in bag.read_messages(topics=[args.topic]):
            times.append(msg.header.stamp.to_sec())
            p = msg.pose.pose.position
            pos.append((p.x, p.y, p.z))

    if len(times) < 2:
        raise RuntimeError(f"Need at least 2 odometry messages on {args.topic}; found {len(times)}")

    length = [0.0] * len(times)
    vel = [(0.0, 0.0, 0.0)] * len(times)

    for i in range(1, len(times)):
        dx = pos[i][0] - pos[i-1][0]
        dy = pos[i][1] - pos[i-1][1]
        dz = pos[i][2] - pos[i-1][2]
        length[i] = length[i-1] + math.sqrt(dx*dx + dy*dy + dz*dz)

    for i in range(len(times)-1):
        dt = times[i+1] - times[i]
        if dt > 0:
            vel[i] = (
                (pos[i+1][0] - pos[i][0]) / dt,
                (pos[i+1][1] - pos[i][1]) / dt,
                (pos[i+1][2] - pos[i][2]) / dt,
            )

    dt = times[-1] - times[-2]
    if dt > 0:
        vel[-1] = (
            (pos[-1][0] - pos[-2][0]) / dt,
            (pos[-1][1] - pos[-2][1]) / dt,
            (pos[-1][2] - pos[-2][2]) / dt,
        )

    with open(args.output, "w") as f:
        f.write("#epsg 0\n")
        f.write(f"#name {args.name}\n")
        f.write("#nframe enu\n")
        f.write("#sorting time\n")
        f.write("#fields t,l,px,py,pz,vx,vy,vz\n")
        for i in range(len(times)):
            f.write(
                f"{times[i]:.9f},"
                f"{length[i]:.9f},"
                f"{pos[i][0]:.9f},"
                f"{pos[i][1]:.9f},"
                f"{pos[i][2]:.9f},"
                f"{vel[i][0]:.9f},"
                f"{vel[i][1]:.9f},"
                f"{vel[i][2]:.9f}\n"
            )

    print(f"Created: {args.output}")
    print(f"Poses: {len(times)}")
    print(f"Duration: {times[-1]-times[0]:.3f} s")
    print(f"Length: {length[-1]:.3f} m")


if __name__ == "__main__":
    main()
