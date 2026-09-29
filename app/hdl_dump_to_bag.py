#!/usr/bin/env python3
"""Convert an hdl_graph_slam dump's FINAL optimized keyframe estimates into a ROS1 Odometry bag."""
import argparse, glob, math, os, re
from pathlib import Path
import numpy as np
import rosbag, rospy
from nav_msgs.msg import Odometry


def parse_data(path):
    text = Path(path).read_text()
    m = re.search(r"stamp\s+(\d+)\s+(\d+)", text)
    if not m:
        raise ValueError(f"No stamp in {path}")
    stamp = int(m.group(1)) + int(m.group(2))*1e-9
    lines = text.splitlines()
    idx = lines.index("estimate")
    mat = np.array([[float(x) for x in line.split()] for line in lines[idx+1:idx+5]], dtype=float)
    return stamp, mat


def mat_to_quat(R):
    tr = float(np.trace(R))
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        qw = 0.25*s
        qx = (R[2,1]-R[1,2])/s
        qy = (R[0,2]-R[2,0])/s
        qz = (R[1,0]-R[0,1])/s
    elif R[0,0] > R[1,1] and R[0,0] > R[2,2]:
        s = math.sqrt(1 + R[0,0]-R[1,1]-R[2,2])*2
        qw = (R[2,1]-R[1,2])/s; qx=.25*s
        qy=(R[0,1]+R[1,0])/s; qz=(R[0,2]+R[2,0])/s
    elif R[1,1] > R[2,2]:
        s = math.sqrt(1 + R[1,1]-R[0,0]-R[2,2])*2
        qw=(R[0,2]-R[2,0])/s; qx=(R[0,1]+R[1,0])/s
        qy=.25*s; qz=(R[1,2]+R[2,1])/s
    else:
        s = math.sqrt(1 + R[2,2]-R[0,0]-R[1,1])*2
        qw=(R[1,0]-R[0,1])/s; qx=(R[0,2]+R[2,0])/s
        qy=(R[1,2]+R[2,1])/s; qz=.25*s
    q=np.array([qx,qy,qz,qw], float); q/=np.linalg.norm(q)
    return q


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--dump', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--topic', default='/hdl_graph_slam/optimized_odometry')
    args=ap.parse_args()
    folders=sorted(glob.glob(os.path.join(args.dump, '[0-9]'*6)))
    rows=[]
    for folder in folders:
        p=os.path.join(folder,'data')
        if os.path.isfile(p): rows.append(parse_data(p))
    rows.sort(key=lambda x:x[0])
    if len(rows)<2: raise RuntimeError(f'Only {len(rows)} optimized keyframes found in {args.dump}')
    with rosbag.Bag(args.output,'w') as bag:
        for stamp, T in rows:
            msg=Odometry(); msg.header.stamp=rospy.Time.from_sec(stamp)
            msg.header.frame_id='map'; msg.child_frame_id='base_link'
            msg.pose.pose.position.x=float(T[0,3]); msg.pose.pose.position.y=float(T[1,3]); msg.pose.pose.position.z=float(T[2,3])
            q=mat_to_quat(T[:3,:3])
            msg.pose.pose.orientation.x=float(q[0]); msg.pose.pose.orientation.y=float(q[1]); msg.pose.pose.orientation.z=float(q[2]); msg.pose.pose.orientation.w=float(q[3])
            bag.write(args.topic,msg,t=msg.header.stamp)
    print(f'Created {args.output}')
    print(f'Optimized keyframes: {len(rows)}')
    print(f'Start: {rows[0][0]:.9f}')
    print(f'End:   {rows[-1][0]:.9f}')

if __name__=='__main__': main()
