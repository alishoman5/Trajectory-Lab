# Setup on the existing Ubuntu installation

The supplied project was exported from a ROS Noetic workspace. This guide restores the project-specific profiles; it does not rebuild or replace the entire ROS environment.

## Dependencies

Use the upstream installation instructions linked in the root README for LIO-SAM, FAST-LIO2 and hdl_graph_slam, including their build dependencies. Preserve the working `~/ws_livox` underlay and `~/catkin_ws` overlay. The HDL helper in `app/` is retained as source material, but it installs unpinned sources and copies its launcher without a backup; prefer the configuration installer below for an existing workspace.

The ROS Python interpreter needs PyQt5, NumPy, ROS message/bag bindings, and a compatible Ouster SDK exposing `ouster.sdk.pcap.pcap_scan_source.PcapScanSource` and `ouster.sdk.client`. The exact working SDK version must be captured from Ubuntu; do not replace it with an untested latest version. `app/requirements.txt` only records the original minimal GUI requirements and is not a complete environment lock.

## Install the project profiles

From this repository on Ubuntu:

```bash
bash scripts/install_profiles.sh ~/catkin_ws
```

The script checks required package directories before changing anything and saves each existing target next to itself with a timestamped backup suffix. It installs the selected NDT_OMP HDL launcher, the FAST-LIO2 launcher/settings, and the LIO-SAM parameters. LIO-SAM's existing upstream `run.launch` and includes are required.

## Separate Trajectopy environment

Use a separately installed compatible Python (the exported setup targets Python 3.10 or newer). Do not replace ROS's system Python. For example, with Python 3.11 already installed:

```bash
python3.11 -m venv ~/.venvs/trajectory_lab_trajectopy
env -u PYTHONPATH -u PYTHONHOME ~/.venvs/trajectory_lab_trajectopy/bin/python -m pip install trajectopy
env -u PYTHONPATH -u PYTHONHOME ~/.venvs/trajectory_lab_trajectopy/bin/python -m pip freeze > trajectopy-environment.txt
```

The package version is not pinned because the working environment was not exported. Validate compatibility by running the comparison on known trajectories and retaining the evaluation metadata. The imported application checks the required ATE API, but that is not a complete numerical compatibility test.

The pipeline detects this venv; alternatively set `TRAJECTOPY_PYTHON` to its Python executable. Run the GUI from a shell with the Noetic, Livox and catkin environments sourced, as shown in the root README.

## Record the working environment

Record `git rev-parse HEAD` and `git status --short` inside each upstream source checkout, the Ouster SDK version, the Trajectopy environment freeze, and any local patches. Keep local path details and machine-specific exports out of published documentation. Version capture is necessary before describing the setup as exactly reproducible.
