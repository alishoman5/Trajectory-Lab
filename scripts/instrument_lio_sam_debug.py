#!/usr/bin/env python3
"""Instrument a ROS1 LIO-SAM checkout with Trajectory Lab CSV diagnostics.

The patch is intentionally narrow and targets the standard TixiaoShan/LIO-SAM
ROS1 source layout. It creates one-time .trajectory_lab_debug.bak backups and
writes runtime diagnostics to $TRAJECTORY_LAB_DEBUG_DIR (or
~/TrajectoryLab_Debug when the variable is not set).
"""

import argparse
import re
from pathlib import Path

MARKER = "TRAJECTORY_LAB_DEBUG_INSTRUMENTED"


def replace_once(text, old, new, label):
    if old not in text:
        raise RuntimeError(f"Could not find expected source block for: {label}. Local LIO-SAM source may differ from upstream.")
    return text.replace(old, new, 1)


def function_span(text, signature):
    """Return [start,end) for a C++ function using brace matching."""
    start = text.find(signature)
    if start < 0:
        raise RuntimeError(f"Could not find function signature: {signature}")
    brace = text.find("{", start)
    if brace < 0:
        raise RuntimeError(f"Could not find opening brace for: {signature}")
    depth = 0
    for idx in range(brace, len(text)):
        ch = text[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return start, idx + 1
    raise RuntimeError(f"Could not find closing brace for: {signature}")


def replace_regex_once(text, pattern, replacement, label, flags=0):
    new, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise RuntimeError(f"Could not find expected source pattern for: {label}")
    return new


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

    # Patch scan2MapOptimization structurally so minor whitespace/local edits do
    # not break the instrumentation.
    fn_start, fn_end = function_span(text, "void scan2MapOptimization()")
    fn = text[fn_start:fn_end]

    fn = replace_regex_once(
        fn,
        r'(if\s*\(cloudKeyPoses3D->points\.empty\(\)\)\s*return\s*;)',
        r'''\1

        bool tlLmConverged = false;
        int tlIterations = 0;
        int tlCornerCorr = 0;
        int tlSurfCorr = 0;
        int tlTotalCorr = 0;''',
        "scan debug state",
        flags=re.S,
    )

    fn = replace_regex_once(
        fn,
        r'(cornerOptimization\s*\(\s*\)\s*;\s*surfOptimization\s*\(\s*\)\s*;)',
        r'''\1

                tlCornerCorr = 0;
                for (int i = 0; i < laserCloudCornerLastDSNum; ++i)
                    if (laserCloudOriCornerFlag[i]) ++tlCornerCorr;
                tlSurfCorr = 0;
                for (int i = 0; i < laserCloudSurfLastDSNum; ++i)
                    if (laserCloudOriSurfFlag[i]) ++tlSurfCorr;''',
        "correspondence counters",
        flags=re.S,
    )

    fn = replace_regex_once(
        fn,
        r'(combineOptimizationCoeffs\s*\(\s*\)\s*;)',
        r'''\1
                tlTotalCorr = (int)laserCloudOri->size();
                tlIterations = iterCount + 1;''',
        "optimization iteration counters",
    )

    fn = replace_regex_once(
        fn,
        r'if\s*\(\s*LMOptimization\s*\(\s*iterCount\s*\)\s*==\s*true\s*\)\s*break\s*;',
        r'''if (LMOptimization(iterCount) == true)
                {
                    tlLmConverged = true;
                    break;
                }''',
        "LM convergence flag",
        flags=re.S,
    )

    debug_tail = r'''

        if (tlMapDebug.is_open())
        {
            tlMapDebug << timeLaserInfoCur << ","
                       << laserCloudCornerLastDSNum << "," << laserCloudSurfLastDSNum << ","
                       << laserCloudCornerFromMapDSNum << "," << laserCloudSurfFromMapDSNum << ","
                       << tlCornerCorr << "," << tlSurfCorr << "," << tlTotalCorr << ","
                       << (isDegenerate ? 1 : 0) << "," << (tlLmConverged ? 1 : 0) << "," << tlIterations << ","
                       << cloudKeyPoses3D->size() << ","
                       << transformTobeMapped[3] << "," << transformTobeMapped[4] << "," << transformTobeMapped[5] << ","
                       << transformTobeMapped[0] << "," << transformTobeMapped[1] << "," << transformTobeMapped[2] << ","
                       << (cloudInfo.imuAvailable ? 1 : 0) << "," << (cloudInfo.odomAvailable ? 1 : 0) << "\n";
            tlMapDebug.flush();
        }
'''
    fn = fn[:-1] + debug_tail + "    }"
    text = text[:fn_start] + fn + text[fn_end:]


    text = replace_regex_once(
        text,
        r'(float\s+noiseScore\s*=\s*icp\.getFitnessScore\s*\(\s*\)\s*;)',
        r'''\1
        if (tlLoopDebug.is_open())
        {
            tlLoopDebug << timeLaserInfoCur << "," << loopKeyCur << "," << loopKeyPre << ","
                        << noiseScore << "," << cureKeyframeCloud->size() << "," << prevKeyframeCloud->size() << "\\n";
            tlLoopDebug.flush();
        }''',
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

    deskew_replacement = r'''bool tlDeskewReady = deskewInfo();
        if (tlDeskewDebug.is_open())
        {
            bool tlImuCovers = !imuQueue.empty() &&
                imuQueue.front().header.stamp.toSec() <= timeScanCur &&
                imuQueue.back().header.stamp.toSec() >= timeScanEnd;
            double tlImuFirst = imuQueue.empty() ? -1.0 : imuQueue.front().header.stamp.toSec();
            double tlImuLast  = imuQueue.empty() ? -1.0 : imuQueue.back().header.stamp.toSec();
            tlDeskewDebug << timeScanCur << "," << timeScanEnd << "," << (timeScanEnd - timeScanCur) << ","
                          << laserCloudIn->size() << "," << imuQueue.size() << "," << tlImuFirst << "," << tlImuLast << ","
                          << (tlImuCovers ? 1 : 0) << "," << (tlDeskewReady ? 1 : 0) << ","
                          << (cloudInfo.imuAvailable ? 1 : 0) << "," << (cloudInfo.odomAvailable ? 1 : 0) << ","
                          << deskewFlag << "," << (imuPointerCur >= 0 ? imuPointerCur + 1 : 0) << ","
                          << (odomDeskewFlag ? 1 : 0) << "\\n";
            tlDeskewDebug.flush();
        }
        if (!tlDeskewReady)
            return;

        projectPointCloud();'''
    text = replace_regex_once(
        text,
        r'if\s*\(\s*!deskewInfo\s*\(\s*\)\s*\)\s*return\s*;\s*projectPointCloud\s*\(\s*\)\s*;',
        deskew_replacement,
        "deskew runtime instrumentation",
        flags=re.S,
    )
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
