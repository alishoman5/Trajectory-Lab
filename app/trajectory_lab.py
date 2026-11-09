#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from PyQt5.QtCore import Qt, QThread, QUrl
from PyQt5.QtGui import QDesktopServices, QFont, QPixmap
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QPlainTextEdit,
    QProgressBar, QScrollArea, QSpinBox, QStackedWidget, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget, QSizePolicy,
    QHeaderView, QAbstractItemView
)

from pipeline import PipelineWorker


APP_DIR = Path(__file__).resolve().parent
ALG_FILE = APP_DIR / "algorithms.json"


STYLE = r"""
QMainWindow, QWidget {
    background: #0f1117;
    color: #e7eaf0;
    font-family: Inter, "DejaVu Sans", sans-serif;
    font-size: 13px;
}
QFrame#sidebar {
    background: #151924;
    border-right: 1px solid #272d3a;
}
QLabel#brand {
    font-size: 20px;
    font-weight: 700;
    color: #f4f6fb;
    padding: 8px 4px 18px 4px;
}
QLabel#subtitle {
    color: #8f98aa;
    font-size: 12px;
}
QPushButton.nav {
    text-align: left;
    padding: 11px 14px;
    border: 0;
    border-radius: 9px;
    background: transparent;
    color: #aeb6c6;
    font-weight: 600;
}
QPushButton.nav:hover { background: #1d2330; color: #ffffff; }
QPushButton.nav:checked { background: #25314a; color: #ffffff; }
QPushButton {
    background: #242b3a;
    color: #f4f6fb;
    border: 1px solid #343d50;
    border-radius: 8px;
    padding: 8px 13px;
    min-height: 18px;
}
QPushButton:hover { background: #2d3648; }
QPushButton#primary {
    background: #3b6cff;
    border-color: #3b6cff;
    font-weight: 700;
}
QPushButton#primary:hover { background: #4d7bff; }
QPushButton#danger {
    background: #3a2024;
    border-color: #6a3037;
}
QPushButton:disabled {
    color: #6f7785;
    background: #1a1e27;
    border-color: #252a35;
}
QLineEdit, QDoubleSpinBox, QSpinBox {
    background: #171b24;
    border: 1px solid #303747;
    border-radius: 8px;
    padding: 8px 10px;
    color: #eef1f7;
    min-height: 20px;
}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus { border-color: #547cff; }
QGroupBox {
    border: 1px solid #282f3d;
    border-radius: 12px;
    margin-top: 12px;
    padding: 14px;
    font-weight: 700;
    background: #141821;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #f1f3f8;
}
QTableWidget {
    background: #131720;
    alternate-background-color: #171c26;
    border: 1px solid #2b3240;
    border-radius: 10px;
    gridline-color: #2a303c;
}
QHeaderView::section {
    background: #1d2330;
    color: #cfd5df;
    padding: 8px;
    border: 0;
    border-right: 1px solid #2d3442;
    font-weight: 700;
}
QPlainTextEdit {
    background: #0b0d12;
    color: #cbd3df;
    border: 1px solid #272d38;
    border-radius: 10px;
    font-family: "DejaVu Sans Mono", monospace;
    font-size: 12px;
}
QProgressBar {
    background: #1a1f29;
    border: 1px solid #303747;
    border-radius: 7px;
    height: 14px;
    text-align: center;
}
QProgressBar::chunk { background: #3b6cff; border-radius: 6px; }
QScrollArea { border: 0; }
QTabWidget::pane { border: 1px solid #2b3240; border-radius: 10px; }
QTabBar::tab {
    background: #171b24;
    color: #9da6b6;
    padding: 9px 14px;
    border: 1px solid #2b3240;
}
QTabBar::tab:selected { background: #252d3d; color: #ffffff; }
QCheckBox { spacing: 8px; }
"""


class PlotLabel(QLabel):
    """Responsive plot viewer that keeps the original high-resolution pixmap."""
    def __init__(self, parent=None):
        super().__init__("Plot will appear after a run.", parent)
        self._source_pixmap = QPixmap()
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(390)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet(
            "background:#f7f8fb;border:1px solid #2a3140;border-radius:9px;"
            "color:#788294;padding:8px;"
        )

    def set_plot(self, path):
        self._source_pixmap = QPixmap()
        if not path or not Path(path).is_file():
            self.clear()
            self.setText("Plot not available for this run.")
            return
        pix = QPixmap(path)
        if pix.isNull():
            self.clear()
            self.setText("Plot could not be loaded.")
            return
        self._source_pixmap = pix
        self.setText("")
        self._rescale()

    def _rescale(self):
        if self._source_pixmap.isNull():
            return
        w = max(320, self.width() - 20)
        h = max(260, self.height() - 20)
        self.setPixmap(self._source_pixmap.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale()


class FileRow(QWidget):
    def __init__(self, label, file_filter, directory=False):
        super().__init__()
        self.file_filter = file_filter
        self.directory = directory
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel(label)
        self.label.setFixedWidth(120)
        self.edit = QLineEdit()
        self.button = QPushButton("Browse")
        self.button.clicked.connect(self.browse)
        layout.addWidget(self.label)
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.button)

    def browse(self):
        if self.directory:
            p = QFileDialog.getExistingDirectory(self, "Select folder", self.edit.text() or str(Path.home()))
        else:
            p, _ = QFileDialog.getOpenFileName(self, "Select file", self.edit.text() or str(Path.home()), self.file_filter)
        if p:
            self.edit.setText(p)

    def text(self):
        return self.edit.text().strip()

    def setText(self, text):
        self.edit.setText(text)


class AlgorithmDialog(QDialog):
    def __init__(self, alg=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Algorithm profile")
        self.resize(620, 320)
        alg = alg or {}
        form = QFormLayout(self)

        self.name = QLineEdit(alg.get("name", ""))
        self.alg_id = QLineEdit(alg.get("id", ""))
        self.command = QLineEdit(alg.get("launch_command", ""))
        self.topic = QLineEdit(alg.get("odom_topic", ""))
        self.delay = QDoubleSpinBox()
        self.delay.setRange(0.0, 60.0)
        self.delay.setDecimals(1)
        self.delay.setValue(float(alg.get("startup_delay", 5.0)))
        self.desc = QLineEdit(alg.get("description", ""))

        form.addRow("Name", self.name)
        form.addRow("ID", self.alg_id)
        form.addRow("Launch command", self.command)
        form.addRow("Odometry topic", self.topic)
        form.addRow("Startup delay [s]", self.delay)
        form.addRow("Description", self.desc)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def data(self):
        alg_id = self.alg_id.text().strip() or self.name.text().lower().replace(" ", "_")
        return {
            "id": alg_id,
            "name": self.name.text().strip() or alg_id,
            "launch_command": self.command.text().strip(),
            "odom_topic": self.topic.text().strip(),
            "startup_delay": float(self.delay.value()),
            "configured": bool(self.command.text().strip() and self.topic.text().strip()),
            "description": self.desc.text().strip(),
        }


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Trajectory Lab")
        self.resize(1500, 900)
        self.setMinimumSize(1180, 720)
        self.algorithms = self.load_algorithms()
        self.algorithm_checks = {}
        self.thread = None
        self.worker = None
        self.last_run = None

        root = QWidget()
        self.setCentralWidget(root)
        main = QHBoxLayout(root)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(225)
        s = QVBoxLayout(sidebar)
        s.setContentsMargins(16, 22, 16, 18)

        brand = QLabel("Trajectory Lab")
        brand.setObjectName("brand")
        sub = QLabel("LiDAR–IMU evaluation")
        sub.setObjectName("subtitle")
        s.addWidget(brand)
        s.addWidget(sub)
        s.addSpacing(16)

        self.stack = QStackedWidget()
        self.nav = []
        pages = [
            ("Dataset", self.make_dataset_page()),
            ("Algorithms", self.make_algorithms_page()),
            ("Run & Compare", self.make_run_page()),
            ("Results", self.make_results_page()),
            ("Console", self.make_console_page()),
        ]
        for i, (name, page) in enumerate(pages):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setProperty("class", "nav")
            b.setStyleSheet("")  # stylesheet class selected by dynamic property below
            b.setObjectName(f"nav_{i}")
            b.clicked.connect(lambda checked, x=i: self.change_page(x))
            b.setProperty("nav", True)
            b.setCursor(Qt.PointingHandCursor)
            s.addWidget(b)
            self.nav.append(b)
            self.stack.addWidget(page)

        # Give nav buttons the nav class via per-button stylesheet selector.
        for b in self.nav:
            b.setStyleSheet(
                "QPushButton {text-align:left;padding:11px 14px;border:0;border-radius:9px;"
                "background:transparent;color:#aeb6c6;font-weight:600;}"
                "QPushButton:hover{background:#1d2330;color:white;}"
                "QPushButton:checked{background:#25314a;color:white;}"
            )

        s.addStretch(1)
        footer = QLabel("ROS1 Noetic\nOuster + SBG workflow")
        footer.setObjectName("subtitle")
        s.addWidget(footer)

        main.addWidget(sidebar)
        main.addWidget(self.stack, 1)
        self.change_page(0)

    def title_block(self, title, subtitle):
        box = QWidget()
        l = QVBoxLayout(box)
        l.setContentsMargins(0, 0, 0, 18)
        h = QLabel(title)
        f = QFont()
        f.setPointSize(20)
        f.setBold(True)
        h.setFont(f)
        d = QLabel(subtitle)
        d.setObjectName("subtitle")
        d.setWordWrap(True)
        l.addWidget(h)
        l.addWidget(d)
        return box

    def page_shell(self):
        outer = QWidget()
        layout = QVBoxLayout(outer)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        return outer, layout

    def make_dataset_page(self):
        page, l = self.page_shell()
        l.addWidget(self.title_block(
            "Dataset",
            "Choose the raw sensor files. Auto-detect can populate a folder containing one Ouster PCAP, metadata JSON, SBG binary log and RTS trajectory."
        ))

        g = QGroupBox("Input files")
        gl = QVBoxLayout(g)
        self.pcap = FileRow("Ouster PCAP", "PCAP (*.pcap);;All files (*)")
        self.metadata = FileRow("Metadata JSON", "JSON (*.json);;All files (*)")
        self.sbg = FileRow("SBG binary", "Binary (*.bin);;All files (*)")
        self.rts = FileRow("RTS trajectory", "Trajectory (*.traj);;All files (*)")
        for row in (self.pcap, self.metadata, self.sbg, self.rts):
            gl.addWidget(row)

        actions = QHBoxLayout()
        auto = QPushButton("Auto-detect folder")
        auto.clicked.connect(self.auto_detect_folder)
        validate = QPushButton("Validate dataset")
        validate.clicked.connect(self.validate_dataset)
        actions.addWidget(auto)
        actions.addWidget(validate)
        actions.addStretch(1)
        gl.addLayout(actions)
        l.addWidget(g)

        g2 = QGroupBox("Output & dataset identity")
        f = QFormLayout(g2)
        self.dataset_name = QLineEdit("dataset")
        self.output_root = FileRow("Output root", "", directory=True)
        self.output_root.setText(str(Path.home() / "TrajectoryLab_Output"))
        f.addRow("Dataset name", self.dataset_name)
        f.addRow(self.output_root)
        l.addWidget(g2)

        self.dataset_status = QLabel("No dataset validated yet.")
        self.dataset_status.setWordWrap(True)
        l.addWidget(self.dataset_status)
        l.addStretch(1)
        return page

    def make_algorithms_page(self):
        page, l = self.page_shell()
        l.addWidget(self.title_block(
            "Algorithms",
            "Select one or more ROS odometry algorithms. Each profile needs a launch command and a nav_msgs/Odometry topic."
        ))

        top = QHBoxLayout()
        add = QPushButton("Add algorithm")
        add.clicked.connect(self.add_algorithm)
        save = QPushButton("Save profiles")
        save.clicked.connect(self.save_algorithms)
        top.addWidget(add)
        top.addWidget(save)
        top.addStretch(1)
        l.addLayout(top)

        self.alg_scroll = QScrollArea()
        self.alg_scroll.setWidgetResizable(True)
        self.alg_container = QWidget()
        self.alg_layout = QVBoxLayout(self.alg_container)
        self.alg_layout.setSpacing(10)
        self.alg_layout.addStretch(1)
        self.alg_scroll.setWidget(self.alg_container)
        l.addWidget(self.alg_scroll, 1)

        self.refresh_algorithm_cards()
        return page

    def make_run_page(self):
        page, l = self.page_shell()
        l.addWidget(self.title_block(
            "Run & Compare",
            "The dataset is converted once, then selected algorithms are executed sequentially against the same synchronized bag."
        ))

        g = QGroupBox("Run settings")
        form = QFormLayout(g)
        self.play_rate = QDoubleSpinBox()
        self.play_rate.setRange(0.1, 5.0)
        self.play_rate.setSingleStep(0.1)
        self.play_rate.setValue(1.0)
        self.max_dt = QDoubleSpinBox()
        self.max_dt.setRange(0.001, 1.0)
        self.max_dt.setDecimals(3)
        self.max_dt.setSingleStep(0.01)
        self.max_dt.setValue(0.05)

        self.rpe_min = QDoubleSpinBox()
        self.rpe_min.setRange(0.1, 1000.0)
        self.rpe_min.setDecimals(1)
        self.rpe_min.setValue(5.0)
        self.rpe_max = QDoubleSpinBox()
        self.rpe_max.setRange(0.1, 5000.0)
        self.rpe_max.setDecimals(1)
        self.rpe_max.setValue(50.0)
        self.rpe_step = QDoubleSpinBox()
        self.rpe_step.setRange(0.1, 1000.0)
        self.rpe_step.setDecimals(1)
        self.rpe_step.setValue(5.0)
        self.rpe_all_pairs = QCheckBox("Use all overlapping pose pairs for RPE")
        self.rpe_all_pairs.setChecked(True)

        self.workspace = QLineEdit("~/catkin_ws")
        self.reuse_bag = QCheckBox("Reuse cached synchronized sensor bag")
        self.reuse_bag.setChecked(True)
        form.addRow("rosbag play rate", self.play_rate)
        form.addRow("Trajectopy max time match [s]", self.max_dt)
        form.addRow("RPE min pair distance [m]", self.rpe_min)
        form.addRow("RPE max pair distance [m]", self.rpe_max)
        form.addRow("RPE distance step [m]", self.rpe_step)
        form.addRow("", self.rpe_all_pairs)
        form.addRow("Catkin workspace", self.workspace)
        form.addRow("", self.reuse_bag)
        l.addWidget(g)

        self.run_summary = QLabel("Choose dataset and algorithms.")
        self.run_summary.setWordWrap(True)
        l.addWidget(self.run_summary)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        l.addWidget(self.progress)
        self.progress_label = QLabel("Idle")
        self.progress_label.setObjectName("subtitle")
        l.addWidget(self.progress_label)

        actions = QHBoxLayout()
        self.run_btn = QPushButton("Run selected algorithms")
        self.run_btn.setObjectName("primary")
        self.run_btn.clicked.connect(self.start_run)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_run)
        actions.addWidget(self.run_btn)
        actions.addWidget(self.stop_btn)
        actions.addStretch(1)
        l.addLayout(actions)
        l.addStretch(1)
        return page

    def make_results_page(self):
        page, l = self.page_shell()
        l.addWidget(self.title_block(
            "Trajectory Evaluation Results",
            "Evaluation backend: Trajectopy • nearest-timestamp pose matching • rigid 6-DoF alignment to RTS (translation + rotation, no scale) • ATE and distance-based RPE."
        ))

        note = QLabel("Ranking metric: ATE mean position error. Lower values are better. Native Trajectopy result files and plots are also exported to the run folder.")
        note.setWordWrap(True)
        note.setStyleSheet("background:#151c2b;border:1px solid #2d3a52;border-radius:8px;padding:9px 12px;color:#b9c6da;")
        l.addWidget(note)

        self.results_tabs = QTabWidget()
        self.results_tabs.setMinimumHeight(205)

        # Main comparison/ranking table. Units are kept in the headers so cells stay compact.
        overview = QWidget()
        ov = QVBoxLayout(overview)
        ov.setContentsMargins(6, 6, 6, 6)
        self.results_table = QTableWidget(0, 10)
        self.results_table.setHorizontalHeaderLabels([
            "Rank", "Algorithm", "ATE Mean [m]", "ATE RMS 3D [m]",
            "ATE Median [m]", "ATE Max [m]", "RPE Pos. Drift [%]",
            "RPE Rot. Drift [deg/100m]", "RPE Pairs", "Matched Poses"
        ])
        self.prepare_table(self.results_table, algorithm_column=1)
        ov.addWidget(self.results_table)
        self.results_tabs.addTab(overview, "Overview")

        # Presentation-oriented interpretation of the same run.  These tables
        # are generated for every algorithm from common RTS speed/distance data.
        insights_page = QWidget()
        insights_l = QVBoxLayout(insights_page)
        self.findings_label = QLabel("Run the algorithms to generate automatic performance findings.")
        self.findings_label.setWordWrap(True)
        self.findings_label.setStyleSheet(
            "background:#151c2b;border:1px solid #2d3a52;border-radius:8px;"
            "padding:12px;color:#d7e3f5;"
        )
        insights_l.addWidget(self.findings_label)
        self.insights_table = QTableWidget(0, 8)
        self.insights_table.setHorizontalHeaderLabels([
            "Algorithm", "Moving ATE Mean [m]", "Speed↔ATE r",
            "Low ATE [m]", "Medium ATE [m]", "High ATE [m]",
            "High−Low [m]", "Moving Poses"
        ])
        self.prepare_table(self.insights_table, algorithm_column=0)
        insights_l.addWidget(self.insights_table)
        self.results_tabs.addTab(insights_page, "Performance Insights")

        failure_page = QWidget()
        failure_l = QVBoxLayout(failure_page)
        failure_note = QLabel(
            "Worst 5 m sections for each algorithm. This shows where an algorithm failed, "
            "instead of reducing the whole dataset to one ATE number."
        )
        failure_note.setObjectName("subtitle")
        failure_note.setWordWrap(True)
        failure_l.addWidget(failure_note)
        self.failure_table = QTableWidget(0, 8)
        self.failure_table.setHorizontalHeaderLabels([
            "Algorithm", "Rank", "Start [m]", "End [m]", "Mean ATE [m]",
            "Max ATE [m]", "Mean Speed [m/s]", "Poses"
        ])
        self.prepare_table(self.failure_table, algorithm_column=0)
        failure_l.addWidget(self.failure_table)
        self.results_tabs.addTab(failure_page, "Failure Segments")

        history_page = QWidget()
        history_l = QVBoxLayout(history_page)
        history_top = QHBoxLayout()
        history_note = QLabel(
            "Latest saved run for each dataset. Use this to answer: which algorithm was best on which dataset?"
        )
        history_note.setObjectName("subtitle")
        history_note.setWordWrap(True)
        refresh_history_btn = QPushButton("Refresh saved datasets")
        refresh_history_btn.clicked.connect(self.refresh_dataset_history)
        history_top.addWidget(history_note, 1)
        history_top.addWidget(refresh_history_btn)
        history_l.addLayout(history_top)
        self.history_table = QTableWidget(0, 9)
        self.history_table.setHorizontalHeaderLabels([
            "Dataset", "Best Overall", "ATE Mean [m]", "ATE RMS [m]",
            "Best Low Speed", "Best Medium Speed", "Best High Speed",
            "Algorithms Tested", "Latest Run"
        ])
        self.prepare_table(self.history_table, algorithm_column=0)
        history_l.addWidget(self.history_table)
        self.results_tabs.addTab(history_page, "Dataset History")

        ate_page = QWidget()
        ate_l = QVBoxLayout(ate_page)
        self.ate_properties_table = QTableWidget(0, 3)
        self.ate_properties_table.setHorizontalHeaderLabels(["Algorithm", "ATE metric (Trajectopy)", "Value"])
        self.prepare_detail_table(self.ate_properties_table)
        ate_l.addWidget(self.ate_properties_table)
        self.results_tabs.addTab(ate_page, "ATE Details")

        rpe_page = QWidget()
        rpe_l = QVBoxLayout(rpe_page)
        self.rpe_properties_table = QTableWidget(0, 3)
        self.rpe_properties_table.setHorizontalHeaderLabels(["Algorithm", "RPE metric (Trajectopy)", "Value"])
        self.prepare_detail_table(self.rpe_properties_table)
        rpe_l.addWidget(self.rpe_properties_table)
        self.results_tabs.addTab(rpe_page, "RPE Details")

        alignment_page = QWidget()
        alignment_l = QVBoxLayout(alignment_page)
        self.alignment_properties_table = QTableWidget(0, 3)
        self.alignment_properties_table.setHorizontalHeaderLabels(["Algorithm", "Alignment parameter", "Value"])
        self.prepare_detail_table(self.alignment_properties_table)
        alignment_l.addWidget(self.alignment_properties_table)
        self.results_tabs.addTab(alignment_page, "Alignment")

        bucket_page = QWidget()
        bucket_l = QVBoxLayout(bucket_page)
        self.rpe_buckets_table = QTableWidget(0, 13)
        self.rpe_buckets_table.setHorizontalHeaderLabels([
            "Algorithm", "Distance [m]", "Pairs",
            "Pos mean [%]", "Pos min [%]", "Pos median [%]", "Pos max [%]", "Pos std [%]",
            "Rot mean [deg/100m]", "Rot min", "Rot median", "Rot max", "Rot std"
        ])
        self.rpe_buckets_table.setAlternatingRowColors(True)
        self.rpe_buckets_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.rpe_buckets_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.rpe_buckets_table.verticalHeader().setVisible(False)
        self.rpe_buckets_table.verticalHeader().setDefaultSectionSize(32)
        bucket_l.addWidget(self.rpe_buckets_table)
        self.results_tabs.addTab(bucket_page, "RPE vs Distance")

        l.addWidget(self.results_tabs, 0)

        self.plot_tabs = QTabWidget()
        self.plot_tabs.setMinimumHeight(440)
        self.plot_xy = self.image_label()
        self.plot_ate = self.image_label()
        self.plot_rpe = self.image_label()
        self.plot_rpe_time = self.image_label()
        self.plot_edf = self.image_label()
        self.plot_ate_bars = self.image_label()
        self.plot_ate_3d = self.image_label()
        self.plot_z = self.image_label()
        self.plot_diag_distance = self.image_label()
        self.plot_diag_speed = self.image_label()
        self.plot_diag_rpe = self.image_label()
        self.plot_diag_scatter = self.image_label()
        self.plot_diag_heatmap = self.image_label()
        self.plot_tabs.addTab(self.wrap_image(self.plot_xy), "Trajectory (XY)")
        self.plot_tabs.addTab(self.wrap_image(self.plot_ate), "3D ATE vs Time")
        self.plot_tabs.addTab(self.wrap_image(self.plot_rpe), "RPE vs Distance")
        self.plot_tabs.addTab(self.wrap_image(self.plot_rpe_time), "RPE vs Time")
        self.plot_tabs.addTab(self.wrap_image(self.plot_edf), "ATE EDF")
        self.plot_tabs.addTab(self.wrap_image(self.plot_ate_bars), "ATE Summary")
        self.plot_tabs.addTab(self.wrap_image(self.plot_ate_3d), "ATE 3D")
        self.plot_tabs.addTab(self.wrap_image(self.plot_z), "Elevation (Z)")
        self.plot_tabs.addTab(self.wrap_image(self.plot_diag_distance), "Errors by Distance")
        self.plot_tabs.addTab(self.wrap_image(self.plot_diag_speed), "Speed Sensitivity")
        self.plot_tabs.addTab(self.wrap_image(self.plot_diag_rpe), "5 m Drift by Speed")
        self.plot_tabs.addTab(self.wrap_image(self.plot_diag_scatter), "ATE vs Speed")
        self.plot_tabs.addTab(self.wrap_image(self.plot_diag_heatmap), "Failure Heatmap")
        l.addWidget(self.plot_tabs, 1)

        row = QHBoxLayout()
        self.load_run_btn = QPushButton("Load / Analyze saved run")
        self.load_run_btn.clicked.connect(self.load_saved_run)
        self.open_output_btn = QPushButton("Open run folder")
        self.open_output_btn.setEnabled(False)
        self.open_output_btn.clicked.connect(self.open_output)
        row.addWidget(self.load_run_btn)
        row.addWidget(self.open_output_btn)
        row.addStretch(1)
        l.addLayout(row)
        return page

    def prepare_table(self, table, algorithm_column=1):
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(34)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(algorithm_column, QHeaderView.Stretch)
        table.setMinimumHeight(165)

    def prepare_detail_table(self, table):
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(31)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)

    def image_label(self):
        return PlotLabel()

    def wrap_image(self, label):
        s = QScrollArea()
        s.setWidgetResizable(True)
        s.setWidget(label)
        s.setFrameShape(QFrame.NoFrame)
        return s

    def make_console_page(self):
        page, l = self.page_shell()
        l.addWidget(self.title_block("Console", "Live pipeline output and ROS process messages."))
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        l.addWidget(self.console, 1)
        row = QHBoxLayout()
        clear = QPushButton("Clear")
        clear.clicked.connect(self.console.clear)
        row.addWidget(clear)
        row.addStretch(1)
        l.addLayout(row)
        return page

    def change_page(self, index):
        self.stack.setCurrentIndex(index)
        for i, b in enumerate(self.nav):
            b.setChecked(i == index)
        if index == 2:
            self.update_run_summary()

    def load_algorithms(self):
        try:
            return json.loads(ALG_FILE.read_text())
        except Exception:
            return []

    def save_algorithms(self):
        ALG_FILE.write_text(json.dumps(self.algorithms, indent=2))
        QMessageBox.information(self, "Saved", "Algorithm profiles saved.")

    def refresh_algorithm_cards(self):
        while self.alg_layout.count() > 1:
            item = self.alg_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self.algorithm_checks = {}

        for alg in self.algorithms:
            box = QGroupBox(alg["name"])
            grid = QGridLayout(box)
            check = QCheckBox("Select for run")
            check.setChecked(alg["id"] == "lio_sam")
            status = QLabel("Configured" if alg.get("launch_command") and alg.get("odom_topic") else "Needs setup")
            status.setStyleSheet("color:#7dd3a7;" if "Configured" in status.text() else "color:#e6b76a;")
            desc = QLabel(alg.get("description", ""))
            desc.setWordWrap(True)
            cmd = QLabel("Launch: " + (alg.get("launch_command") or "—"))
            cmd.setObjectName("subtitle")
            topic = QLabel("Odometry: " + (alg.get("odom_topic") or "—"))
            topic.setObjectName("subtitle")
            edit = QPushButton("Configure")
            edit.clicked.connect(lambda checked, a=alg: self.edit_algorithm(a))
            remove = QPushButton("Remove")
            remove.clicked.connect(lambda checked, a=alg: self.remove_algorithm(a))

            grid.addWidget(check, 0, 0)
            grid.addWidget(status, 0, 1)
            grid.addWidget(edit, 0, 2)
            grid.addWidget(remove, 0, 3)
            grid.addWidget(desc, 1, 0, 1, 4)
            grid.addWidget(cmd, 2, 0, 1, 4)
            grid.addWidget(topic, 3, 0, 1, 4)
            self.alg_layout.insertWidget(self.alg_layout.count()-1, box)
            self.algorithm_checks[alg["id"]] = check

    def add_algorithm(self):
        d = AlgorithmDialog(parent=self)
        if d.exec_() == QDialog.Accepted:
            self.algorithms.append(d.data())
            self.refresh_algorithm_cards()

    def edit_algorithm(self, alg):
        d = AlgorithmDialog(alg, self)
        if d.exec_() == QDialog.Accepted:
            data = d.data()
            idx = self.algorithms.index(alg)
            self.algorithms[idx] = data
            self.refresh_algorithm_cards()

    def remove_algorithm(self, alg):
        if QMessageBox.question(self, "Remove", f"Remove profile '{alg['name']}'?") == QMessageBox.Yes:
            self.algorithms.remove(alg)
            self.refresh_algorithm_cards()

    def auto_detect_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Dataset folder", str(Path.home() / "Downloads"))
        if not folder:
            return
        p = Path(folder)
        pcaps = sorted(p.glob("*.pcap"))
        jsons = sorted(p.glob("*.json"))
        bins = sorted(p.glob("*.bin"))
        trajs = sorted(p.glob("*.traj"))
        if pcaps: self.pcap.setText(str(pcaps[0]))
        if jsons: self.metadata.setText(str(jsons[0]))
        sbg_bins = [x for x in bins if x.name.lower().startswith("sbg")]
        if sbg_bins: self.sbg.setText(str(sbg_bins[0]))
        elif bins: self.sbg.setText(str(bins[0]))
        rts_trajs = [x for x in trajs if x.name.lower().startswith("rts")]
        if rts_trajs:
            self.rts.setText(str(rts_trajs[0]))
        elif trajs:
            self.rts.setText(str(trajs[0]))
        self.dataset_name.setText(p.name)
        self.validate_dataset()

    def validate_dataset(self):
        paths = {
            "pcap": self.pcap.text(),
            "metadata": self.metadata.text(),
            "sbg": self.sbg.text(),
            "rts": self.rts.text(),
        }
        missing = [k for k, v in paths.items() if not v or not Path(v).is_file()]
        if missing:
            self.dataset_status.setText("Missing or invalid: " + ", ".join(missing))
            self.dataset_status.setStyleSheet("color:#ef9090;")
            return False
        try:
            meta = json.loads(Path(paths["metadata"]).read_text())
            text = json.dumps(meta)
            required = ["TIME_FROM_SYNC_PULSE_IN", "INPUT_NMEA_UART", "nmea_leap_seconds"]
            timing_ok = all(x in text for x in required)
            timing_msg = "Ouster PPS/NMEA timing profile detected." if timing_ok else "Metadata does not match the current PPS/NMEA converter profile."
            self.dataset_status.setText("All files found. " + timing_msg)
            self.dataset_status.setStyleSheet("color:#7dd3a7;" if timing_ok else "color:#e6b76a;")
            return timing_ok
        except Exception as e:
            self.dataset_status.setText(f"Metadata error: {e}")
            self.dataset_status.setStyleSheet("color:#ef9090;")
            return False

    def selected_algorithms(self):
        out = []
        for alg in self.algorithms:
            cb = self.algorithm_checks.get(alg["id"])
            if cb and cb.isChecked():
                out.append(dict(alg))
        return out

    def update_run_summary(self):
        algs = self.selected_algorithms()
        names = ", ".join(a["name"] for a in algs) or "none"
        self.run_summary.setText(
            f"Dataset: {self.dataset_name.text().strip() or 'dataset'}\n"
            f"Algorithms: {names}\n"
            f"RPE distance buckets: {self.rpe_min.value():.1f}–{self.rpe_max.value():.1f} m, step {self.rpe_step.value():.1f} m\n"
            f"Sensor bag conversion: {'reuse cache when available' if self.reuse_bag.isChecked() else 'rebuild every run'}"
        )

    def start_run(self):
        if not self.validate_dataset():
            QMessageBox.warning(self, "Dataset", "Fix dataset validation before running.")
            self.change_page(0)
            return
        selected = self.selected_algorithms()
        if not selected:
            QMessageBox.warning(self, "Algorithms", "Select at least one algorithm.")
            self.change_page(1)
            return
        unconfigured = [a["name"] for a in selected if not a.get("launch_command") or not a.get("odom_topic")]
        if unconfigured:
            QMessageBox.warning(self, "Algorithms", "Configure these profiles first:\n" + "\n".join(unconfigured))
            self.change_page(1)
            return

        out_root = self.output_root.text()
        if not out_root:
            QMessageBox.warning(self, "Output", "Choose an output folder.")
            return

        dataset = {
            "pcap": self.pcap.text(),
            "metadata": self.metadata.text(),
            "sbg": self.sbg.text(),
            "rts": self.rts.text(),
        }
        options = {
            "dataset_name": self.dataset_name.text().strip() or "dataset",
            "output_root": out_root,
            "reuse_sensor_bag": self.reuse_bag.isChecked(),
            "play_rate": self.play_rate.value(),
            "max_dt": self.max_dt.value(),
            "rpe_min": self.rpe_min.value(),
            "rpe_max": self.rpe_max.value(),
            "rpe_step": self.rpe_step.value(),
            "rpe_all_pairs": self.rpe_all_pairs.isChecked(),
            "workspace": self.workspace.text().strip() or "~/catkin_ws",
            "flush_delay": 2.0,
        }

        self.console.clear()
        self.results_table.setRowCount(0)
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress.setValue(0)
        self.progress_label.setText("Starting...")
        self.change_page(2)

        self.thread = QThread()
        self.worker = PipelineWorker(APP_DIR, dataset, selected, options)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.log.connect(self.append_log)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.failed.connect(self.on_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def stop_run(self):
        if self.worker:
            self.worker.request_stop()
        self.stop_btn.setEnabled(False)

    def append_log(self, text):
        self.console.appendPlainText(text)

    def on_progress(self, value, label):
        self.progress.setValue(value)
        self.progress_label.setText(label)

    def on_failed(self, message):
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_label.setText("Failed")
        self.append_log("ERROR: " + message)
        QMessageBox.critical(self, "Pipeline failed", message)
        self.change_page(4)

    def on_finished(self, result):
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.last_run = result
        self.populate_results(result["metrics"])
        self.populate_diagnostics(result.get("diagnostics", {}))
        self.load_plot(self.plot_xy, result["plots"].get("xy", ""))
        self.load_plot(self.plot_ate, result["plots"].get("ate", result["plots"].get("error", "")))
        self.load_plot(self.plot_rpe, result["plots"].get("rpe", ""))
        self.load_plot(self.plot_rpe_time, result["plots"].get("rpe_time", ""))
        self.load_plot(self.plot_edf, result["plots"].get("ate_edf", ""))
        self.load_plot(self.plot_ate_bars, result["plots"].get("ate_bars_position", ""))
        self.load_plot(self.plot_ate_3d, result["plots"].get("ate_3d", ""))
        self.load_plot(self.plot_z, result["plots"].get("z", ""))
        diag_plots = result.get("diagnostics", {}).get("plots", {})
        self.load_plot(self.plot_diag_distance, diag_plots.get("ate_distance", ""))
        self.load_plot(self.plot_diag_speed, diag_plots.get("speed_ate", ""))
        self.load_plot(self.plot_diag_rpe, diag_plots.get("speed_rpe", ""))
        self.load_plot(self.plot_diag_scatter, diag_plots.get("ate_speed", ""))
        self.load_plot(self.plot_diag_heatmap, diag_plots.get("segment_heatmap", ""))
        self.refresh_dataset_history()
        self.open_output_btn.setEnabled(True)
        self.progress_label.setText("Finished")
        self.change_page(3)

    def populate_results(self, metrics):
        self.results_table.setRowCount(len(metrics))
        for row, m in enumerate(metrics):
            ate = m.get("ate", {})
            rpe = m.get("rpe", {})
            ate_mean = ate.get("pos_mean_m", m.get("ate_mean_m", m.get("mean_error_m", 0.0)))
            rms_3d = ate.get("pos_rms_m", m.get("rms_3d_m", m.get("ate_rmse_m", 0.0)))
            median = ate.get("pos_median_m", m.get("median_error_m", 0.0))
            maxerr = ate.get("pos_max_m", m.get("max_error_m", 0.0))
            rpe_pos = rpe.get("mean_position_drift", m.get("rpe_position"))
            rpe_pos_unit = rpe.get("position_drift_unit", m.get("rpe_position_unit", "%"))
            rpe_rot = rpe.get("mean_rotation_drift_deg_per_100m", m.get("rpe_rotation_deg_per_100m"))
            vals = [
                str(m.get("rank", row + 1)), m.get("name", ""),
                f"{ate_mean:.4f}", f"{rms_3d:.4f}", f"{median:.4f}", f"{maxerr:.4f}",
                (f"{rpe_pos:.4f}" if rpe_pos is not None else "N/A"),
                (f"{rpe_rot:.4f}" if rpe_rot is not None else "N/A"),
                str(rpe.get("num_pairs_total", m.get("rpe_pairs", 0))),
                str(m.get("matched_samples", 0)),
            ]
            for col, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setTextAlignment(Qt.AlignCenter if col != 1 else Qt.AlignLeft | Qt.AlignVCenter)
                self.results_table.setItem(row, col, item)
        self.results_table.resizeRowsToContents()

        self.populate_property_table(self.ate_properties_table, metrics, "ate_properties")
        self.populate_property_table(self.rpe_properties_table, metrics, "rpe_properties")
        self.populate_property_table(self.alignment_properties_table, metrics, "alignment_properties")

        bucket_rows = []
        for m in metrics:
            for b in m.get("rpe", {}).get("per_distance", []):
                bucket_rows.append((m.get("name", ""), b))
        self.rpe_buckets_table.setRowCount(len(bucket_rows))
        for row, (name, b) in enumerate(bucket_rows):
            def fmt(v, nd=4):
                return "N/A" if v is None else f"{v:.{nd}f}"
            vals = [
                name, fmt(b.get("distance_m"), 2), str(b.get("pairs", 0)),
                fmt(b.get("pos_mean")), fmt(b.get("pos_min")), fmt(b.get("pos_median")),
                fmt(b.get("pos_max")), fmt(b.get("pos_std")),
                fmt(b.get("rot_mean_deg_per_100m")), fmt(b.get("rot_min_deg_per_100m")),
                fmt(b.get("rot_median_deg_per_100m")), fmt(b.get("rot_max_deg_per_100m")),
                fmt(b.get("rot_std_deg_per_100m")),
            ]
            for col, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setTextAlignment(Qt.AlignCenter if col != 0 else Qt.AlignLeft | Qt.AlignVCenter)
                self.rpe_buckets_table.setItem(row, col, item)
        self.rpe_buckets_table.resizeColumnsToContents()

    def populate_diagnostics(self, diagnostics):
        """Populate presentation-oriented diagnostic tables for the current run."""
        diagnostics = diagnostics or {}
        findings = diagnostics.get("findings", []) or []
        if findings:
            self.findings_label.setText("\n".join(f"• {x}" for x in findings))
        else:
            self.findings_label.setText(
                "Performance diagnostics were not generated for this run. "
                "Core Trajectopy results above are still valid."
            )

        algorithms = diagnostics.get("algorithms", []) or []
        self.insights_table.setRowCount(len(algorithms))
        for row, a in enumerate(algorithms):
            bins = a.get("speed_bins", {}) or {}
            def bmean(key):
                v = (bins.get(key, {}) or {}).get("mean")
                return None if v is None else float(v)
            low, medium, high = bmean("low"), bmean("medium"), bmean("high")
            delta = (high - low) if high is not None and low is not None else None
            moving_mean = (a.get("moving_ate", {}) or {}).get("mean")
            corr = a.get("speed_ate_correlation")
            vals = [
                a.get("name", ""),
                "N/A" if moving_mean is None else f"{float(moving_mean):.4f}",
                "N/A" if corr is None else f"{float(corr):+.3f}",
                "N/A" if low is None else f"{low:.4f}",
                "N/A" if medium is None else f"{medium:.4f}",
                "N/A" if high is None else f"{high:.4f}",
                "N/A" if delta is None else f"{delta:+.4f}",
                str(a.get("moving_poses", 0)),
            ]
            for col, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter if col == 0 else Qt.AlignCenter)
                self.insights_table.setItem(row, col, item)
        self.insights_table.resizeRowsToContents()

        rows = []
        for a in algorithms:
            for rank, seg in enumerate(a.get("worst_segments", []) or [], 1):
                rows.append((a.get("name", ""), rank, seg))
        self.failure_table.setRowCount(len(rows))
        for row, (name, rank, seg) in enumerate(rows):
            vals = [
                name, str(rank),
                f"{float(seg.get('distance_start_m', 0.0)):.1f}",
                f"{float(seg.get('distance_end_m', 0.0)):.1f}",
                f"{float(seg.get('mean_ate_m', 0.0)):.4f}",
                f"{float(seg.get('max_ate_m', 0.0)):.4f}",
                f"{float(seg.get('mean_speed_m_s', 0.0)):.3f}",
                str(seg.get("poses", 0)),
            ]
            for col, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter if col == 0 else Qt.AlignCenter)
                self.failure_table.setItem(row, col, item)
        self.failure_table.resizeRowsToContents()

    def refresh_dataset_history(self):
        """Show the latest saved run per dataset from the selected output root."""
        try:
            root = Path(os.path.expanduser(self.output_root.text())).resolve()
        except Exception:
            return
        latest = {}
        if root.is_dir():
            for metrics_path in root.glob("*/comparison/summary_metrics.json"):
                run_dir = metrics_path.parent.parent
                try:
                    metrics = json.loads(metrics_path.read_text())
                    if not metrics:
                        continue
                    meta_path = run_dir / "run_metadata.json"
                    if meta_path.exists():
                        try:
                            dataset = json.loads(meta_path.read_text()).get("dataset_name") or run_dir.name
                        except Exception:
                            dataset = run_dir.name
                    else:
                        dataset = re.sub(r"_\d{8}_\d{6}$", "", run_dir.name)
                    if dataset in latest and latest[dataset]["run"] >= run_dir.name:
                        continue
                    def ate_mean(m):
                        ate = m.get("ate", {}) or {}
                        v = ate.get("pos_mean_m", m.get("ate_mean_m", m.get("mean_error_m")))
                        return float(v) if v is not None else float("inf")
                    def ate_rms(m):
                        ate = m.get("ate", {}) or {}
                        v = ate.get("pos_rms_m", m.get("rms_3d_m", m.get("ate_rmse_m")))
                        return float(v) if v is not None else float("inf")
                    best = min(metrics, key=ate_mean)
                    speeds = {"low": "—", "medium": "—", "high": "—"}
                    perf = metrics_path.parent / "performance_analysis.json"
                    if perf.exists():
                        try:
                            pd = json.loads(perf.read_text())
                            for k in speeds:
                                b = (pd.get("best_by_speed", {}) or {}).get(k)
                                if b:
                                    speeds[k] = b.get("name", "—")
                        except Exception:
                            pass
                    latest[dataset] = {
                        "run": run_dir.name,
                        "best": best.get("name", ""),
                        "mean": ate_mean(best),
                        "rms": ate_rms(best),
                        "low": speeds["low"],
                        "medium": speeds["medium"],
                        "high": speeds["high"],
                        "count": len(metrics),
                    }
                except Exception:
                    continue
        rows = sorted(latest.items(), key=lambda x: x[0].lower())
        self.history_table.setRowCount(len(rows))
        for row, (dataset, d) in enumerate(rows):
            vals = [
                dataset, d["best"], f"{d['mean']:.4f}", f"{d['rms']:.4f}",
                d["low"], d["medium"], d["high"], str(d["count"]), d["run"],
            ]
            for col, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter if col in (0, 1, 4, 5, 6, 8) else Qt.AlignCenter)
                self.history_table.setItem(row, col, item)
        self.history_table.resizeRowsToContents()

    def populate_property_table(self, table, metrics, key):
        rows = []
        for m in metrics:
            props = m.get(key, {}) or {}
            for prop, value in props.items():
                rows.append((m.get("name", ""), str(prop), str(value)))
        table.setRowCount(len(rows))
        for row, vals in enumerate(rows):
            for col, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                table.setItem(row, col, item)
        table.resizeColumnsToContents()

    def load_plot(self, label, path):
        if isinstance(label, PlotLabel):
            label.set_plot(path)
            return
        if not path or not Path(path).is_file():
            label.setText("Plot not available for this run.")
            label.setPixmap(QPixmap())
            return
        pix = QPixmap(path)
        label.setPixmap(pix)

    def load_saved_run(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select a Trajectory Lab run folder",
            self.output_root.text() or str(Path.home() / "TrajectoryLab_Output")
        )
        if not folder:
            return
        run_dir = Path(folder).resolve()
        results_dir = run_dir / "comparison"
        metrics_file = results_dir / "summary_metrics.json"
        manifest = run_dir / "comparison_manifest.json"
        if not metrics_file.is_file() or not manifest.is_file():
            QMessageBox.warning(
                self, "Not a Trajectory Lab run",
                "The selected folder must contain comparison_manifest.json and comparison/summary_metrics.json."
            )
            return
        try:
            metrics = json.loads(metrics_file.read_text())
            perf_file = results_dir / "performance_analysis.json"
            if not perf_file.exists():
                meta = run_dir / "run_metadata.json"
                if meta.exists():
                    try:
                        dataset_name = json.loads(meta.read_text()).get("dataset_name") or run_dir.name
                    except Exception:
                        dataset_name = run_dir.name
                else:
                    dataset_name = re.sub(r"_\d{8}_\d{6}$", "", run_dir.name)
                script = APP_DIR / "performance_analysis.py"
                cmd = [
                    sys.executable, str(script),
                    "--manifest", str(manifest),
                    "--metrics", str(metrics_file),
                    "--out-dir", str(results_dir),
                    "--dataset-name", dataset_name,
                    "--output-root", str(run_dir.parent),
                ]
                proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                self.append_log(proc.stdout)
                if proc.returncode != 0:
                    raise RuntimeError(proc.stdout[-3000:])
            diagnostics = json.loads(perf_file.read_text()) if perf_file.exists() else {}
            result = {
                "run_dir": str(run_dir),
                "metrics": metrics,
                "diagnostics": diagnostics,
                "plots": {
                    "xy": str(results_dir / "combined_xy.png"),
                    "z": str(results_dir / "combined_z.png"),
                    "ate": str(results_dir / "gui_ate_vs_time.png"),
                    "rpe": str(results_dir / "gui_rpe_vs_distance.png"),
                    "rpe_time": str(results_dir / "trajectopy_rpe_time.png"),
                    "ate_edf": str(results_dir / "trajectopy_ate_edf.png"),
                    "ate_bars_position": str(results_dir / "trajectopy_ate_bars_position.png"),
                    "ate_3d": str(results_dir / "trajectopy_ate_3d.png"),
                },
            }
            self.on_finished(result)
        except Exception as e:
            QMessageBox.critical(self, "Could not load run", str(e))

    def open_output(self):
        if self.last_run:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_run["run_dir"]))


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()