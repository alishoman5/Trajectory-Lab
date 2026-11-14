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
            "Choose the raw sensor files. RTS is optional: when it is not provided, Trajectory Lab builds a local reference from SBG GNSS/navigation data."
        ))

        g = QGroupBox("Input files")
        gl = QVBoxLayout(g)
        self.pcap = FileRow("Ouster PCAP", "PCAP (*.pcap);;All files (*)")
        self.metadata = FileRow("Metadata JSON", "JSON (*.json);;All files (*)")
        self.sbg = FileRow("SBG binary", "Binary (*.bin);;All files (*)")
        self.rts = FileRow("RTS trajectory (optional)", "Trajectory (*.traj);;All files (*)")
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
            "Trajectory Evaluation",
            "Focused view: overall accuracy, where errors occur, and which motion conditions are associated with them. "
            "Detailed Trajectopy audit files remain available under comparison/raw/."
        ))

        self.reference_note = QLabel(
            "ATE and RPE use the selected reference trajectory: RTS when available, otherwise an SBG GNSS/GNSS-INS fallback. "
            "Alignment is rigid 6-DoF (translation + rotation, no scale). GNSS fallback accuracy is lower than RTS and must be interpreted accordingly. "
            "Motion correlations are diagnostic associations, not proof of causation."
        )
        self.reference_note.setWordWrap(True)
        self.reference_note.setStyleSheet(
            "background:#151c2b;border:1px solid #2d3a52;border-radius:8px;"
            "padding:9px 12px;color:#b9c6da;"
        )
        l.addWidget(self.reference_note)

        self.results_tabs = QTabWidget()
        self.results_tabs.setMinimumHeight(205)

        # 1) Is the algorithm accurate overall?
        overview = QWidget()
        ov = QVBoxLayout(overview)
        ov.setContentsMargins(6, 6, 6, 6)
        self.results_table = QTableWidget(0, 7)
        self.results_table.setHorizontalHeaderLabels([
            "Rank", "Algorithm", "ATE Mean [m]", "ATE RMS [m]",
            "ATE Max [m]", "RPE Pos. Drift [%]", "Matched Poses"
        ])
        self.prepare_table(self.results_table, algorithm_column=1)
        ov.addWidget(self.results_table)
        self.results_tabs.addTab(overview, "Overview")

        # 2) Under which motion conditions does error increase?
        diagnostics_page = QWidget()
        diagnostics_l = QVBoxLayout(diagnostics_page)
        self.findings_label = QLabel("Run or load a dataset to generate diagnostic findings.")
        self.findings_label.setWordWrap(True)
        self.findings_label.setStyleSheet(
            "background:#151c2b;border:1px solid #2d3a52;border-radius:8px;"
            "padding:12px;color:#d7e3f5;"
        )
        diagnostics_l.addWidget(self.findings_label)
        self.insights_table = QTableWidget(0, 10)
        self.insights_table.setHorizontalHeaderLabels([
            "Algorithm", "Moving ATE [m]", "Speed↔ATE r", "Ref Accel↔ATE r",
            "IMU Accel↔ATE r", "Angular↔ATE r",
            "Low-speed ATE [m]", "Medium-speed ATE [m]", "High-speed ATE [m]", "Moving Poses"
        ])
        self.prepare_table(self.insights_table, algorithm_column=0)
        diagnostics_l.addWidget(self.insights_table)
        self.results_tabs.addTab(diagnostics_page, "Motion Diagnostics")

        # 3) Where are the worst sections?
        failure_page = QWidget()
        failure_l = QVBoxLayout(failure_page)
        failure_note = QLabel(
            "Worst 5 m sections. Compare error with RTS motion, gravity-compensated SBG acceleration and measured angular velocity before forming a failure hypothesis."
        )
        failure_note.setObjectName("subtitle")
        failure_note.setWordWrap(True)
        failure_l.addWidget(failure_note)
        self.failure_table = QTableWidget(0, 11)
        self.failure_table.setHorizontalHeaderLabels([
            "Algorithm", "Rank", "Start [m]", "End [m]", "Mean ATE [m]",
            "Max ATE [m]", "Mean Speed [m/s]", "Mean Ref Accel [m/s²]",
            "Mean IMU Accel [m/s²]", "Mean Angular [rad/s]", "Poses"
        ])
        self.prepare_table(self.failure_table, algorithm_column=0)
        failure_l.addWidget(self.failure_table)
        self.results_tabs.addTab(failure_page, "Failure Segments")

        l.addWidget(self.results_tabs, 0)

        # Only plots that answer a concrete evaluation question are shown.
        self.plot_tabs = QTabWidget()
        self.plot_tabs.setMinimumHeight(440)
        self.plot_xy = self.image_label()
        self.plot_rpe = self.image_label()
        self.plot_diag_distance = self.image_label()
        self.plot_diag_scatter = self.image_label()
        self.plot_diag_acceleration = self.image_label()
        self.plot_diag_imu_acceleration = self.image_label()
        self.plot_diag_angular = self.image_label()
        self.plot_diag_heatmap = self.image_label()

        self.plot_tabs.addTab(self.wrap_image(self.plot_xy), "Trajectory vs Reference")
        self.plot_tabs.addTab(self.wrap_image(self.plot_diag_distance), "ATE Along Route")
        self.plot_tabs.addTab(self.wrap_image(self.plot_rpe), "RPE vs Distance")
        self.plot_tabs.addTab(self.wrap_image(self.plot_diag_scatter), "ATE vs Speed")
        self.plot_tabs.addTab(self.wrap_image(self.plot_diag_acceleration), "ATE vs Reference Acceleration")
        self.plot_tabs.addTab(self.wrap_image(self.plot_diag_imu_acceleration), "ATE vs IMU Acceleration")
        self.plot_tabs.addTab(self.wrap_image(self.plot_diag_angular), "ATE vs Angular Velocity")
        self.plot_tabs.addTab(self.wrap_image(self.plot_diag_heatmap), "Failure Heatmap")
        l.addWidget(self.plot_tabs, 1)

        row = QHBoxLayout()
        self.load_run_btn = QPushButton("Load / Analyze saved run")
        self.load_run_btn.clicked.connect(self.load_saved_run)
        self.self_test_btn = QPushButton("Run evaluator self-test")
        self.self_test_btn.clicked.connect(self.run_evaluator_self_test)
        self.open_output_btn = QPushButton("Open run folder")
        self.open_output_btn.setEnabled(False)
        self.open_output_btn.clicked.connect(self.open_output)
        self.open_raw_btn = QPushButton("Open raw audit files")
        self.open_raw_btn.setEnabled(False)
        self.open_raw_btn.clicked.connect(self.open_raw_output)
        row.addWidget(self.load_run_btn)
        row.addWidget(self.self_test_btn)
        row.addWidget(self.open_output_btn)
        row.addWidget(self.open_raw_btn)
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
        self.rts.setText("")
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
        required_paths = ("pcap", "metadata", "sbg")
        missing = [k for k in required_paths if not paths[k] or not Path(paths[k]).is_file()]
        if missing:
            self.dataset_status.setText("Missing or invalid: " + ", ".join(missing))
            self.dataset_status.setStyleSheet("color:#ef9090;")
            return False

        if paths["rts"] and not Path(paths["rts"]).is_file():
            self.dataset_status.setText("RTS path is invalid. Clear it to use SBG GNSS fallback.")
            self.dataset_status.setStyleSheet("color:#ef9090;")
            return False

        try:
            meta = json.loads(Path(paths["metadata"]).read_text())
            text = json.dumps(meta)
            required = ["TIME_FROM_SYNC_PULSE_IN", "INPUT_NMEA_UART", "nmea_leap_seconds"]
            timing_ok = all(x in text for x in required)
            timing_msg = "Ouster PPS/NMEA timing profile detected." if timing_ok else "Metadata does not match the current PPS/NMEA converter profile."

            if paths["rts"]:
                ref_msg = "Reference: RTS trajectory."
            else:
                ref_msg = "Reference: SBG GNSS fallback will be generated at run time."

            self.dataset_status.setText(f"Core files found. {ref_msg} {timing_msg}")
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
        reference = "RTS Ground Truth" if self.rts.text() else "SBG GNSS fallback"
        self.run_summary.setText(
            f"Dataset: {self.dataset_name.text().strip() or 'dataset'}\n"
            f"Reference: {reference}\n"
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
        reference_label = result.get("reference_label", "Reference")
        reference_source = result.get("reference_source", "")
        self.reference_note.setText(
            f"Reference used: {reference_label} ({reference_source}). "
            "ATE/RPE are computed after nearest-timestamp matching and rigid 6-DoF alignment "
            "(translation + rotation, no scale). If the reference is SBG GNSS/GNSS-INS, its own positioning uncertainty limits how the error should be interpreted."
        )
        self.populate_results(result["metrics"])
        self.populate_diagnostics(result.get("diagnostics", {}))

        self.load_plot(self.plot_xy, result["plots"].get("xy", ""))
        self.load_plot(self.plot_rpe, result["plots"].get("rpe", ""))

        diag_plots = result.get("diagnostics", {}).get("plots", {})
        self.load_plot(self.plot_diag_distance, diag_plots.get("ate_distance", ""))
        self.load_plot(self.plot_diag_scatter, diag_plots.get("ate_speed", ""))
        self.load_plot(self.plot_diag_acceleration, diag_plots.get("ate_acceleration", ""))
        self.load_plot(self.plot_diag_imu_acceleration, diag_plots.get("ate_imu_linear_acceleration", ""))
        self.load_plot(self.plot_diag_angular, diag_plots.get("ate_angular_velocity", ""))
        self.load_plot(self.plot_diag_heatmap, diag_plots.get("segment_heatmap", ""))

        self.open_output_btn.setEnabled(True)
        self.open_raw_btn.setEnabled(True)
        self.progress_label.setText("Finished")
        self.change_page(3)

    def populate_results(self, metrics):
        self.results_table.setRowCount(len(metrics))
        for row, m in enumerate(metrics):
            ate = m.get("ate", {}) or {}
            rpe = m.get("rpe", {}) or {}
            ate_mean = ate.get("pos_mean_m", m.get("ate_mean_m", m.get("mean_error_m", 0.0)))
            rms_3d = ate.get("pos_rms_m", m.get("rms_3d_m", m.get("ate_rmse_m", 0.0)))
            maxerr = ate.get("pos_max_m", m.get("max_error_m", 0.0))
            rpe_pos = rpe.get("mean_position_drift", m.get("rpe_position"))
            vals = [
                str(m.get("rank", row + 1)),
                m.get("name", ""),
                f"{float(ate_mean):.4f}",
                f"{float(rms_3d):.4f}",
                f"{float(maxerr):.4f}",
                "N/A" if rpe_pos is None else f"{float(rpe_pos):.4f}",
                str(m.get("matched_samples", 0)),
            ]
            for col, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setTextAlignment(Qt.AlignCenter if col != 1 else Qt.AlignLeft | Qt.AlignVCenter)
                self.results_table.setItem(row, col, item)
        self.results_table.resizeRowsToContents()

    def populate_diagnostics(self, diagnostics):
        """Populate focused motion and failure diagnostics for every algorithm."""
        diagnostics = diagnostics or {}
        findings = diagnostics.get("findings", []) or []
        if findings:
            self.findings_label.setText("\n".join(f"• {x}" for x in findings))
        else:
            self.findings_label.setText(
                "Diagnostics are unavailable for this run. Core Trajectopy ATE/RPE results remain valid."
            )

        algorithms = diagnostics.get("algorithms", []) or []
        self.insights_table.setRowCount(len(algorithms))
        for row, a in enumerate(algorithms):
            bins = a.get("speed_bins", {}) or {}
            def bmean(key):
                v = (bins.get(key, {}) or {}).get("mean")
                return None if v is None else float(v)

            low, medium, high = bmean("low"), bmean("medium"), bmean("high")
            moving_mean = (a.get("moving_ate", {}) or {}).get("mean")
            speed_corr = a.get("speed_ate_correlation")
            accel_corr = a.get("acceleration_ate_correlation")
            imu_accel_corr = a.get("imu_linear_acceleration_ate_correlation")
            angular_corr = a.get("angular_velocity_ate_correlation")
            vals = [
                a.get("name", ""),
                "N/A" if moving_mean is None else f"{float(moving_mean):.4f}",
                "N/A" if speed_corr is None else f"{float(speed_corr):+.3f}",
                "N/A" if accel_corr is None else f"{float(accel_corr):+.3f}",
                "N/A" if imu_accel_corr is None else f"{float(imu_accel_corr):+.3f}",
                "N/A" if angular_corr is None else f"{float(angular_corr):+.3f}",
                "N/A" if low is None else f"{low:.4f}",
                "N/A" if medium is None else f"{medium:.4f}",
                "N/A" if high is None else f"{high:.4f}",
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
                "N/A" if seg.get("mean_acceleration_m_s2") is None else f"{float(seg.get('mean_acceleration_m_s2')):.3f}",
                "N/A" if seg.get("mean_imu_linear_acceleration_m_s2") is None else f"{float(seg.get('mean_imu_linear_acceleration_m_s2')):.3f}",
                "N/A" if seg.get("mean_angular_velocity_rad_s") is None else f"{float(seg.get('mean_angular_velocity_rad_s')):.3f}",
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
            manifest_data = json.loads(manifest.read_text())
            perf_file = results_dir / "performance_analysis.json"

            # Re-run the lightweight diagnostics every time a saved run is loaded.
            # This lets older runs gain newly added diagnostics without replaying ROS.
            meta = run_dir / "run_metadata.json"
            meta_data = {}
            if meta.exists():
                try:
                    meta_data = json.loads(meta.read_text())
                    dataset_name = meta_data.get("dataset_name") or run_dir.name
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
            sbg_path = meta_data.get("sbg")
            if sbg_path and Path(sbg_path).is_file():
                cmd.extend(["--sbg", sbg_path])

            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            self.append_log(proc.stdout)
            if proc.returncode != 0:
                raise RuntimeError(proc.stdout[-3000:])
            diagnostics = json.loads(perf_file.read_text()) if perf_file.exists() else {}
            result = {
                "run_dir": str(run_dir),
                "metrics": metrics,
                "reference_label": manifest_data.get("reference_label", "RTS Ground Truth"),
                "reference_source": manifest_data.get("reference_source", "RTS"),
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

    def open_raw_output(self):
        if not self.last_run:
            return
        raw_dir = Path(self.last_run.get("results_dir", Path(self.last_run["run_dir"]) / "comparison")) / "raw"
        if raw_dir.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(raw_dir)))
        else:
            QMessageBox.information(self, "Raw audit files", "No raw audit folder exists for this run.")

    def run_evaluator_self_test(self):
        """Run deterministic synthetic checks against the same evaluator used by the GUI."""
        script = APP_DIR / "validate_evaluator.py"
        if not script.is_file():
            QMessageBox.warning(self, "Evaluator self-test", f"Missing {script.name}")
            return

        candidates = [
            os.environ.get("TRAJECTOPY_PYTHON", "").strip(),
            str(Path.home() / ".venvs" / "trajectory_lab_trajectopy" / "bin" / "python"),
            sys.executable,
        ]
        python_bin = next((p for p in candidates if p and Path(p).is_file()), sys.executable)
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        try:
            proc = subprocess.run(
                [python_bin, str(script)],
                cwd=str(APP_DIR),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=120,
            )
            self.append_log(proc.stdout)
            if proc.returncode == 0:
                QMessageBox.information(self, "Evaluator self-test", "PASS\n\n" + proc.stdout[-2500:])
            else:
                QMessageBox.critical(self, "Evaluator self-test", "FAIL\n\n" + proc.stdout[-3500:])
        except Exception as e:
            QMessageBox.critical(self, "Evaluator self-test", str(e))


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()