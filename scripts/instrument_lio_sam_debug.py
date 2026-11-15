#!/usr/bin/env python3
"""Instrument a ROS1 LIO-SAM checkout with Trajectory Lab CSV diagnostics.

The patch is intentionally narrow and targets the standard TixiaoShan/LIO-SAM
ROS1 source layout. It creates one-time .trajectory_lab_debug.bak backups and
writes runtime diagnostics to $TRAJECTORY_LAB_DEBUG_DIR (or
~/TrajectoryLab_Debug when the variable is not set).
"""

import argparse
from pathlib import Path

MARKER = "TRAJECTORY_LAB_DEBUG_INSTRUMENTED"


def replace_once(text, old, new, label):
    if old not in text:
        raise RuntimeError(f"Could not find expected source block for: {label}. Local LIO-SAM source may differ from upstream.")
    return text.replace(old, new, 1)


def patch_map(path: Path):
    text = path.read_text(encoding="utf-8")
    if MARKER in text:
        print(f"Already instrumented: {path}")
        return
    backup = path.with_suffix(path.suffix + ".trajectory_lab_debug.bak")
    if not backup.exists():
        backup.write_text(text, encoding="utf-8")

    text = replace_once(
        text,
        '#include <gtsam/nonlinear/ISAM2.h>\n',
        '#include <gtsam/nonlinear/ISAM2.h>\n#include <fstream>\n#include <cstdlib>\n// TRAJECTORY_LAB_DEBUG_INSTRUMENTED\n',
        "map includes",
    )

    text = replace_once(
        text,
        '    bool isDegenerate = false;\n    cv::Mat matP;\n',
        '    bool isDegenerate = false;\n    cv::Mat matP;\n\n'
        '    std::ofstream tlMapDebug;\n'
        '    std::ofstream tlLoopDebug;\n',
        "map debug members",
    )

    text = replace_once(
        text,
        '        allocateMemory();\n    }\n',
        '        allocateMemory();\n\n'
        '        const char* tlEnv = std::getenv("TRAJECTORY_LAB_DEBUG_DIR");\n'
        '        std::string tlDebugDir;\n'
        '        if (tlEnv && std::string(tlEnv).size() > 0)\n'
        '            tlDebugDir = std::string(tlEnv);\n'
        '        else {\n'
        '            const char* home = std::getenv("HOME");\n'
        '            tlDebugDir = std::string(home ? home : "/tmp") + "/TrajectoryLab_Debug";\n'
        '        }\n'
        '        std::string tlMkdir = "mkdir -p \\\"" + tlDebugDir + "\\\"";\n'
        '        std::system(tlMkdir.c_str());\n'
        '        tlMapDebug.open((tlDebugDir + "/lio_sam_map_debug.csv").c_str(), std::ios::out | std::ios::trunc);\n'
        '        tlLoopDebug.open((tlDebugDir + "/lio_sam_loop_debug.csv").c_str(), std::ios::out | std::ios::trunc);\n'
        '        tlMapDebug << "time,corner_scan,surf_scan,corner_map,surf_map,corner_corr,surf_corr,total_corr,is_degenerate,lm_converged,lm_iterations,keyframes,x,y,z,roll,pitch,yaw,imu_available,odom_available\\n";\n'
        '        tlLoopDebug << "time,current_key,previous_key,fitness,current_cloud_points,previous_cloud_points\\n";\n'
        '        tlMapDebug.flush();\n'
        '        tlLoopDebug.flush();\n'
        '    }\n',
        "map constructor debug open",
    )

    old_scan = '''    void scan2MapOptimization()\n    {\n        if (cloudKeyPoses3D->points.empty())\n            return;\n        if (laserCloudCornerLastDSNum > edgeFeatureMinValidNum && laserCloudSurfLastDSNum > surfFeatureMinValidNum)\n        {\n            kdtreeCornerFromMap->setInputCloud(laserCloudCornerFromMapDS);\n            kdtreeSurfFromMap->setInputCloud(laserCloudSurfFromMapDS);\n\n            for (int iterCount = 0; iterCount < 30; iterCount++)\n            {\n                laserCloudOri->clear();\n                coeffSel->clear();\n\n                cornerOptimization();\n                surfOptimization();\n                combineOptimizationCoeffs();\n\n                if (LMOptimization(iterCount) == true)\n                    break;\n            }\n\n            transformUpdate();\n        } else {\n            ROS_WARN("Not enough features! Only %d edge and %d planar features available.", laserCloudCornerLastDSNum, laserCloudSurfLastDSNum);\n        }\n    }\n'''
    new_scan = '''    void scan2MapOptimization()\n    {\n        if (cloudKeyPoses3D->points.empty())\n            return;\n\n        bool tlLmConverged = false;\n        int tlIterations = 0;\n        int tlCornerCorr = 0;\n        int tlSurfCorr = 0;\n        int tlTotalCorr = 0;\n\n        if (laserCloudCornerLastDSNum > edgeFeatureMinValidNum && laserCloudSurfLastDSNum > surfFeatureMinValidNum)\n        {\n            kdtreeCornerFromMap->setInputCloud(laserCloudCornerFromMapDS);\n            kdtreeSurfFromMap->setInputCloud(laserCloudSurfFromMapDS);\n\n            for (int iterCount = 0; iterCount < 30; iterCount++)\n            {\n                laserCloudOri->clear();\n                coeffSel->clear();\n\n                cornerOptimization();\n                surfOptimization();\n\n                tlCornerCorr = 0;\n                for (int i = 0; i < laserCloudCornerLastDSNum; ++i)\n                    if (laserCloudOriCornerFlag[i]) ++tlCornerCorr;\n                tlSurfCorr = 0;\n                for (int i = 0; i < laserCloudSurfLastDSNum; ++i)\n                    if (laserCloudOriSurfFlag[i]) ++tlSurfCorr;\n\n                combineOptimizationCoeffs();\n                tlTotalCorr = (int)laserCloudOri->size();\n                tlIterations = iterCount + 1;\n\n                if (LMOptimization(iterCount) == true)\n                {\n                    tlLmConverged = true;\n                    break;\n                }\n            }\n\n            transformUpdate();\n        } else {\n            ROS_WARN("Not enough features! Only %d edge and %d planar features available.", laserCloudCornerLastDSNum, laserCloudSurfLastDSNum);\n        }\n\n        if (tlMapDebug.is_open())\n        {\n            tlMapDebug << timeLaserInfoCur << ","\n                       << laserCloudCornerLastDSNum << "," << laserCloudSurfLastDSNum << ","\n                       << laserCloudCornerFromMapDSNum << "," << laserCloudSurfFromMapDSNum << ","\n                       << tlCornerCorr << "," << tlSurfCorr << "," << tlTotalCorr << ","\n                       << (isDegenerate ? 1 : 0) << "," << (tlLmConverged ? 1 : 0) << "," << tlIterations << ","\n                       << cloudKeyPoses3D->size() << ","\n                       << transformTobeMapped[3] << "," << transformTobeMapped[4] << "," << transformTobeMapped[5] << ","\n                       << transformTobeMapped[0] << "," << transformTobeMapped[1] << "," << transformTobeMapped[2] << ","\n                       << (cloudInfo.imuAvailable ? 1 : 0) << "," << (cloudInfo.odomAvailable ? 1 : 0) << "\\n";\n            tlMapDebug.flush();\n        }\n    }\n'''
    text = replace_once(text, old_scan, new_scan, "scan2MapOptimization instrumentation")

    text = replace_once(
        text,
        '        float noiseScore = icp.getFitnessScore();\n        Vector6 << noiseScore, noiseScore, noiseScore, noiseScore, noiseScore, noiseScore;\n',
        '        float noiseScore = icp.getFitnessScore();\n'
        '        if (tlLoopDebug.is_open())\n'
        '        {\n'
        '            tlLoopDebug << timeLaserInfoCur << "," << loopKeyCur << "," << loopKeyPre << ","\n'
        '                        << noiseScore << "," << cureKeyframeCloud->size() << "," << prevKeyframeCloud->size() << "\\n";\n'
        '            tlLoopDebug.flush();\n'
        '        }\n'
        '        Vector6 << noiseScore, noiseScore, noiseScore, noiseScore, noiseScore, noiseScore;\n',
        "loop acceptance instrumentation",
    )

    path.write_text(text, encoding="utf-8")
    print(f"Instrumented: {path}")


def patch_image(path: Path):
    text = path.read_text(encoding="utf-8")
    if MARKER in text:
        print(f"Already instrumented: {path}")
        return
    backup = path.with_suffix(path.suffix + ".trajectory_lab_debug.bak")
    if not backup.exists():
        backup.write_text(text, encoding="utf-8")

    text = replace_once(
        text,
        '#include "lio_sam/cloud_info.h"\n',
        '#include "lio_sam/cloud_info.h"\n#include <fstream>\n#include <cstdlib>\n// TRAJECTORY_LAB_DEBUG_INSTRUMENTED\n',
        "image includes",
    )
    text = replace_once(
        text,
        '    lio_sam::cloud_info cloudInfo;\n',
        '    lio_sam::cloud_info cloudInfo;\n    std::ofstream tlDeskewDebug;\n',
        "deskew debug member",
    )
    text = replace_once(
        text,
        '        resetParameters();\n\n        pcl::console::setVerbosityLevel(pcl::console::L_ERROR);\n',
        '        resetParameters();\n\n'
        '        const char* tlEnv = std::getenv("TRAJECTORY_LAB_DEBUG_DIR");\n'
        '        std::string tlDebugDir;\n'
        '        if (tlEnv && std::string(tlEnv).size() > 0)\n'
        '            tlDebugDir = std::string(tlEnv);\n'
        '        else {\n'
        '            const char* home = std::getenv("HOME");\n'
        '            tlDebugDir = std::string(home ? home : "/tmp") + "/TrajectoryLab_Debug";\n'
        '        }\n'
        '        std::string tlMkdir = "mkdir -p \\\"" + tlDebugDir + "\\\"";\n'
        '        std::system(tlMkdir.c_str());\n'
        '        tlDeskewDebug.open((tlDebugDir + "/lio_sam_deskew_debug.csv").c_str(), std::ios::out | std::ios::trunc);\n'
        '        tlDeskewDebug << "scan_start,scan_end,scan_duration,points,imu_queue,imu_first,imu_last,imu_covers_scan,deskew_ready,imu_available,odom_available,deskew_flag,imu_samples,odom_deskew_flag\\n";\n'
        '        tlDeskewDebug.flush();\n\n'
        '        pcl::console::setVerbosityLevel(pcl::console::L_ERROR);\n',
        "image constructor debug open",
    )

    old = '''        if (!deskewInfo())\n            return;\n\n        projectPointCloud();\n'''
    new = '''        bool tlDeskewReady = deskewInfo();\n        if (tlDeskewDebug.is_open())\n        {\n            bool tlImuCovers = !imuQueue.empty() &&\n                imuQueue.front().header.stamp.toSec() <= timeScanCur &&\n                imuQueue.back().header.stamp.toSec() >= timeScanEnd;\n            double tlImuFirst = imuQueue.empty() ? -1.0 : imuQueue.front().header.stamp.toSec();\n            double tlImuLast  = imuQueue.empty() ? -1.0 : imuQueue.back().header.stamp.toSec();\n            tlDeskewDebug << timeScanCur << "," << timeScanEnd << "," << (timeScanEnd - timeScanCur) << ","\n                          << laserCloudIn->size() << "," << imuQueue.size() << "," << tlImuFirst << "," << tlImuLast << ","\n                          << (tlImuCovers ? 1 : 0) << "," << (tlDeskewReady ? 1 : 0) << ","\n                          << (cloudInfo.imuAvailable ? 1 : 0) << "," << (cloudInfo.odomAvailable ? 1 : 0) << ","\n                          << deskewFlag << "," << (imuPointerCur >= 0 ? imuPointerCur + 1 : 0) << ","\n                          << (odomDeskewFlag ? 1 : 0) << "\\n";\n            tlDeskewDebug.flush();\n        }\n        if (!tlDeskewReady)\n            return;\n\n        projectPointCloud();\n'''
    text = replace_once(text, old, new, "deskew runtime instrumentation")
    path.write_text(text, encoding="utf-8")
    print(f"Instrumented: {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lio-sam-dir", default="~/catkin_ws/src/LIO-SAM")
    args = ap.parse_args()
    root = Path(args.lio_sam_dir).expanduser().resolve()
    map_src = root / "src" / "mapOptmization.cpp"
    image_src = root / "src" / "imageProjection.cpp"
    if not map_src.is_file() or not image_src.is_file():
        raise SystemExit(f"Could not find standard LIO-SAM sources under {root}")
    patch_map(map_src)
    patch_image(image_src)
    print("\nDone. Rebuild your catkin workspace before the next run.")
    print("Backups use the suffix .trajectory_lab_debug.bak")


if __name__ == "__main__":
    main()
