import json
import os
import shlex
import shutil
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import QObject, pyqtSignal


class PipelineWorker(QObject):
    log = pyqtSignal(str)
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, project_dir, dataset, algorithms, options):
        super().__init__()
        self.project_dir = Path(project_dir)
        self.dataset = dataset
        self.algorithms = algorithms
        self.options = options
        self.stop_requested = False
        self.processes = []

    def request_stop(self):
        self.stop_requested = True
        self.log.emit("Stop requested. Terminating active processes...")
        for p in list(self.processes):
            self._terminate(p)

    def _emit(self, text):
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log.emit(f"[{stamp}] {text}")

    def _ros_prefix(self):
        workspace = os.path.expanduser(self.options.get("workspace", "~/catkin_ws"))
        return (
            "source /opt/ros/noetic/setup.bash && "
            f"source {shlex.quote(workspace)}/devel/setup.bash && "
        )

    def _run(self, command, cwd=None, stream=True):
        if self.stop_requested:
            raise RuntimeError("Run stopped by user.")
        full = self._ros_prefix() + command
        self._emit("$ " + command)
        p = subprocess.Popen(
            ["bash", "-lc", full],
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            preexec_fn=os.setsid,
        )
        self.processes.append(p)
        lines = []
        try:
            for line in p.stdout:
                s = line.rstrip()
                lines.append(s)
                if stream and s:
                    self.log.emit(s)
                if self.stop_requested:
                    self._terminate(p)
                    raise RuntimeError("Run stopped by user.")
            rc = p.wait()
        finally:
            if p in self.processes:
                self.processes.remove(p)
        if rc != 0:
            tail = "\n".join(lines[-30:])
            raise RuntimeError(f"Command failed ({rc}): {command}\n{tail}")
        return "\n".join(lines)


    def _find_trajectopy_python(self):
        """Find a Python interpreter with the modern Trajectopy API.

        Trajectopy main requires Python >=3.10 while ROS Noetic on Ubuntu 20.04
        commonly runs Python 3.8.  The bundled setup script therefore creates
        an isolated venv and this function prefers it automatically.
        """
        candidates = []
        env_python = os.environ.get("TRAJECTOPY_PYTHON", "").strip()
        if env_python:
            candidates.append(os.path.expanduser(env_python))
        candidates.append(os.path.expanduser("~/.venvs/trajectory_lab_trajectopy/bin/python"))
        system_py = shutil.which("python3")
        if system_py:
            candidates.append(system_py)

        test_code = (
            "import inspect, trajectopy as t; "
            "s=inspect.signature(t.ate); "
            "req={'trajectory','other','processing_settings','return_alignment','align'}; "
            "assert req.issubset(s.parameters); "
            "print(getattr(t,'__version__','unknown'))"
        )

        checked = []
        for candidate in candidates:
            if not candidate or candidate in checked:
                continue
            checked.append(candidate)
            if not (os.path.isfile(candidate) and os.access(candidate, os.X_OK)):
                continue
            try:
                proc = subprocess.run(
                    [candidate, "-c", test_code],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=15,
                )
            except Exception:
                continue
            if proc.returncode == 0:
                version = proc.stdout.strip() or "unknown"
                self._emit(f"Trajectopy evaluator: {candidate} (version {version})")
                return candidate

        setup = self.project_dir / "setup_trajectopy.sh"
        raise RuntimeError(
            "Modern Trajectopy is not available for the evaluator.\n"
            "Run this once, then start the GUI again:\n"
            f"  cd {self.project_dir}\n"
            f"  chmod +x {setup.name}\n"
            f"  ./{setup.name}"
        )

    def _start_background(self, command, log_file, cwd=None):
        full = self._ros_prefix() + command
        self._emit("$ " + command)
        fh = open(log_file, "w")
        p = subprocess.Popen(
            ["bash", "-lc", full],
            cwd=str(cwd) if cwd else None,
            stdout=fh,
            stderr=subprocess.STDOUT,
            text=True,
            preexec_fn=os.setsid,
        )
        p._trajectory_log_fh = fh
        self.processes.append(p)
        return p

    def _terminate(self, p):
        try:
            if p.poll() is None:
                os.killpg(os.getpgid(p.pid), signal.SIGINT)
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(os.getpgid(p.pid), signal.SIGTERM)
                    try:
                        p.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except Exception:
            pass
        try:
            fh = getattr(p, "_trajectory_log_fh", None)
            if fh:
                fh.close()
        except Exception:
            pass
        if p in self.processes:
            self.processes.remove(p)

    def _ensure_roscore(self, run_dir):
        check = subprocess.run(
            ["bash", "-lc", self._ros_prefix() + "rosnode list >/dev/null 2>&1"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if check.returncode == 0:
            self._emit("Using the existing ROS master.")
            return None
        p = self._start_background("roscore", run_dir / "roscore.log", run_dir)
        for _ in range(30):
            time.sleep(0.5)
            ok = subprocess.run(
                ["bash", "-lc", self._ros_prefix() + "rosnode list >/dev/null 2>&1"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ).returncode == 0
            if ok:
                self._emit("Temporary roscore started.")
                return p
        self._terminate(p)
        raise RuntimeError("roscore did not start.")

    def _safe_id(self, text):
        return "".join(c if c.isalnum() or c in "-_" else "_" for c in text).strip("_") or "algorithm"

    def run(self):
        started_roscore = None
        previous_use_sim_time = None
        try:
            root_out = Path(os.path.expanduser(self.options["output_root"])).resolve()
            root_out.mkdir(parents=True, exist_ok=True)

            dataset_name = self._safe_id(self.options.get("dataset_name", "dataset"))
            run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            run_dir = root_out / f"{dataset_name}_{run_stamp}"
            run_dir.mkdir(parents=True, exist_ok=True)
            cache_dir = root_out / "_cache"
            cache_dir.mkdir(exist_ok=True)
            sensor_bag = cache_dir / f"{dataset_name}_sensor.bag"

            self.progress.emit(3, "Validating dataset")
            for key in ("pcap", "metadata", "sbg", "rts"):
                p = Path(os.path.expanduser(self.dataset[key]))
                if not p.is_file():
                    raise RuntimeError(f"Missing {key}: {p}")

            self._emit(f"Run directory: {run_dir}")

            reuse = bool(self.options.get("reuse_sensor_bag", True))
            if reuse and sensor_bag.exists():
                self.progress.emit(10, "Reusing synchronized sensor bag")
                self._emit(f"Reusing cached sensor bag: {sensor_bag}")
            else:
                self.progress.emit(8, "Converting Ouster LiDAR")
                lidar = self.project_dir / "ouster_to_bag.py"
                cmd = (
                    f"python3 {shlex.quote(str(lidar))} "
                    f"--pcap {shlex.quote(self.dataset['pcap'])} "
                    f"--metadata {shlex.quote(self.dataset['metadata'])} "
                    f"--output {shlex.quote(str(sensor_bag))}"
                )
                self._run(cmd, run_dir)

                self.progress.emit(18, "Converting SBG IMU")
                imu = self.project_dir / "sbg_to_bag.py"
                cmd = (
                    f"python3 {shlex.quote(str(imu))} "
                    f"--sbg {shlex.quote(self.dataset['sbg'])} "
                    f"--append-to {shlex.quote(str(sensor_bag))}"
                )
                self._run(cmd, run_dir)

            self.progress.emit(25, "Preparing ROS")
            started_roscore = self._ensure_roscore(run_dir)

            # Preserve /use_sim_time when reusing a user's ROS master.
            try:
                out = subprocess.check_output(
                    ["bash", "-lc", self._ros_prefix() + "rosparam get /use_sim_time 2>/dev/null || true"],
                    text=True
                ).strip()
                if out in ("true", "false"):
                    previous_use_sim_time = out
            except Exception:
                pass

            self._run("rosparam set /use_sim_time true", run_dir, stream=False)

            estimates = []
            total = len(self.algorithms)
            for idx, alg in enumerate(self.algorithms):
                if self.stop_requested:
                    raise RuntimeError("Run stopped by user.")
                alg_id = self._safe_id(alg["id"])
                name = alg["name"]
                topic = alg["odom_topic"]
                launch_cmd = alg["launch_command"].strip()
                if not launch_cmd:
                    raise RuntimeError(f"{name} has no launch command. Configure it in Algorithms.")

                base = 28 + int((idx / max(total, 1)) * 50)
                self.progress.emit(base, f"Starting {name}")
                alg_log = run_dir / f"{alg_id}.log"
                alg_proc = self._start_background(launch_cmd, alg_log, run_dir)
                time.sleep(float(alg.get("startup_delay", 5.0)))
                if alg_proc.poll() is not None:
                    self._terminate(alg_proc)
                    raise RuntimeError(f"{name} exited during startup. Check {alg_log}")

                result_bag = run_dir / f"{alg_id}_result.bag"
                result_mode = alg.get("result_mode", "odometry_topic")

                if result_mode == "hdl_graph_dump":
                    # hdl_graph_slam's /odom is scan-matching odometry BEFORE graph
                    # optimization. For a fair SLAM comparison we wait until playback
                    # is complete, call /hdl_graph_slam/dump, and convert the FINAL
                    # optimized keyframe `estimate` poses to a synthetic Odometry bag.
                    self.progress.emit(base + 8, f"Playing dataset for {name}")
                    play_cmd = (
                        f"rosbag play {shlex.quote(str(sensor_bag))} --clock --delay=1 "
                        f"--rate={float(self.options.get('play_rate', 1.0))}"
                    )
                    self._run(play_cmd, run_dir)
                    time.sleep(max(3.0, float(self.options.get("flush_delay", 2.0))))

                    dump_dir = run_dir / f"{alg_id}_dump"
                    if dump_dir.exists():
                        import shutil
                        shutil.rmtree(dump_dir)
                    dump_yaml = f"destination: '{dump_dir}'"
                    self.progress.emit(base + 14, f"Dumping optimized graph for {name}")
                    self._run(
                        f"rosservice call /hdl_graph_slam/dump {shlex.quote(dump_yaml)}",
                        run_dir,
                    )
                    self._terminate(alg_proc)

                    helper = self.project_dir / "hdl_dump_to_bag.py"
                    synth_topic = alg.get("optimized_topic", topic)
                    cmd = (
                        f"python3 {shlex.quote(str(helper))} "
                        f"--dump {shlex.quote(str(dump_dir))} "
                        f"--output {shlex.quote(str(result_bag))} "
                        f"--topic {shlex.quote(synth_topic)}"
                    )
                    self._run(cmd, run_dir)
                    topic = synth_topic

                else:
                    record_log = run_dir / f"{alg_id}_record.log"
                    record_cmd = f"rosbag record -O {shlex.quote(str(result_bag))} {shlex.quote(topic)}"
                    rec_proc = self._start_background(record_cmd, record_log, run_dir)
                    time.sleep(1.5)
                    if rec_proc.poll() is not None:
                        self._terminate(alg_proc)
                        raise RuntimeError(f"rosbag record failed for {name}. Check {record_log}")

                    self.progress.emit(base + 8, f"Playing dataset for {name}")
                    play_cmd = (
                        f"rosbag play {shlex.quote(str(sensor_bag))} --clock --delay=1 "
                        f"--rate={float(self.options.get('play_rate', 1.0))}"
                    )
                    self._run(play_cmd, run_dir)
                    time.sleep(float(self.options.get("flush_delay", 2.0)))

                    self._terminate(rec_proc)
                    self._terminate(alg_proc)

                if not result_bag.exists():
                    raise RuntimeError(f"No result bag created for {name}")

                traj = run_dir / f"{alg_id}.traj"
                exporter = self.project_dir / "bag_to_traj.py"
                export_cmd = (
                    f"python3 {shlex.quote(str(exporter))} {shlex.quote(str(result_bag))} "
                    f"--topic {shlex.quote(topic)} --output {shlex.quote(str(traj))} "
                    f"--name {shlex.quote(name)}"
                )
                self._run(export_cmd, run_dir)

                estimates.append({
                    "id": alg_id,
                    "name": name,
                    "bag": str(result_bag),
                    "topic": topic,
                    "traj": str(traj),
                })

            self.progress.emit(82, "Comparing trajectories with Trajectopy")
            manifest = {
                "rts": str(Path(self.dataset["rts"]).resolve()),
                "estimates": estimates,
            }
            manifest_path = run_dir / "comparison_manifest.json"
            manifest_path.write_text(json.dumps(manifest, indent=2))

            results_dir = run_dir / "comparison"
            comparator = self.project_dir / "compare_multi.py"
            trajectopy_python = self._find_trajectopy_python()
            # Remove ROS Noetic's Python 3.8 PYTHONPATH before entering the
            # dedicated Python >=3.10 Trajectopy environment.
            compare_cmd = (
                f"env -u PYTHONPATH -u PYTHONHOME {shlex.quote(trajectopy_python)} "
                f"{shlex.quote(str(comparator))} "
                f"--manifest {shlex.quote(str(manifest_path))} "
                f"--out-dir {shlex.quote(str(results_dir))} "
                f"--max-dt {float(self.options.get('max_dt', 0.05))} "
                f"--rpe-min {float(self.options.get('rpe_min', 5.0))} "
                f"--rpe-max {float(self.options.get('rpe_max', 50.0))} "
                f"--rpe-step {float(self.options.get('rpe_step', 5.0))} "
                f"--rpe-all-pairs {1 if self.options.get('rpe_all_pairs', True) else 0}"
            )
            self._run(compare_cmd, run_dir)

            metrics_file = results_dir / "summary_metrics.json"
            metrics = json.loads(metrics_file.read_text())

            self.progress.emit(100, "Finished")
            self.finished.emit({
                "run_dir": str(run_dir),
                "sensor_bag": str(sensor_bag),
                "metrics": metrics,
                "results_dir": str(results_dir),
                "plots": {
                    # Clean GUI previews generated from Trajectopy result objects.
                    "xy": str(results_dir / "combined_xy.png"),
                    "z": str(results_dir / "combined_z.png"),
                    "ate": str(results_dir / "gui_ate_vs_time.png"),
                    "rpe": str(results_dir / "gui_rpe_vs_distance.png"),
                    # Native Trajectopy plots remain available in the run folder.
                    "rpe_time": str(results_dir / "trajectopy_rpe_time.png"),
                    "ate_edf": str(results_dir / "trajectopy_ate_edf.png"),
                    "ate_bars_position": str(results_dir / "trajectopy_ate_bars_position.png"),
                    "ate_3d": str(results_dir / "trajectopy_ate_3d.png"),
                    "error": str(results_dir / "combined_error.png"),
                },
            })

        except Exception as e:
            self.failed.emit(str(e))
        finally:
            for p in list(self.processes):
                self._terminate(p)

            if previous_use_sim_time is not None and started_roscore is None:
                try:
                    subprocess.run(
                        ["bash", "-lc", self._ros_prefix() + f"rosparam set /use_sim_time {previous_use_sim_time}"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except Exception:
                    pass
            if started_roscore is not None:
                self._terminate(started_roscore)
