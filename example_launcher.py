#!/usr/bin/env python3
"""
Poco CAN Example GUI Launcher
=====================

Launcher for the Poco CAN example applications.

Run with:
    python3 example_launcher.py
"""

import sys
import os
import subprocess
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QLabel, QPushButton, QFrame)
from PyQt5.QtGui import QFont

class LauncherGUI(QMainWindow):
    """Simple launcher for Poco CAN applications."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Poco CAN GUI Launcher")
        self.setGeometry(200, 200, 420, 380)

        self.setStyleSheet("""
            QMainWindow {
                background-color: #1a1a1a;
            }
            QWidget {
                background-color: #1a1a1a;
                color: #ffffff;
            }
            QPushButton {
                background-color: #404040;
                border: 1px solid #606060;
                border-radius: 6px;
                padding: 12px 20px;
                color: #ffffff;
                font-size: 15px;
                text-align: center;
            }
            QPushButton:hover {
                background-color: #505050;
            }
            QPushButton:pressed {
                background-color: #353535;
            }
        """)

        self._setup_ui()

    def _setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)
        layout.setSpacing(20)
        layout.setContentsMargins(30, 30, 30, 30)

        # Title
        title = QLabel("Poco CAN Protocol Examples")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Arial", 20, QFont.Bold))
        layout.addWidget(title)

        subtitle = QLabel("Choose the protocol level for your application:")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setFont(QFont("Arial", 11))
        layout.addWidget(subtitle)

        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background-color: #606060;")
        layout.addWidget(line)

        # Get the script directory to build absolute paths
        script_dir = os.path.dirname(os.path.abspath(__file__))

        # Example Application buttons - organized by protocol level
        apps = [
            ("Level 2: Virtual Switches (Actions)",
             "Full-featured lighting control with colors, patterns, dimming (Proprietary VSw Actions)",
             os.path.join(script_dir, "examples/vsw_lev2_gui.py")),

            ("Level 1: Virtual Switches as Binary On/Off",
             "Control Poco Virtual Switches using NMEA2000 Binary Switch protocol (PGN 127501/127502)",
             os.path.join(script_dir, "examples/vsw_lev1_gui.py")),

            ("Level 0: Output Channel Control (Hardware)",
             "Direct hardware channel commands - PLI, PWM, Binary (PGN 61184 PIDs 6-8,16)",
             os.path.join(script_dir, "examples/channel_lev0_util.py")),
        ]

        for name, tooltip, script in apps:
            btn = QPushButton(name)
            btn.setMinimumHeight(50)
            btn.setToolTip(tooltip)
            btn.clicked.connect(lambda checked, s=script: self._launch_app(s))
            layout.addWidget(btn)

        layout.addStretch()

        # Info
        info = QLabel("Choose a protocol level for your application. Each level provides progressively more capabilities.")
        info.setAlignment(Qt.AlignCenter)
        info.setFont(QFont("Arial", 9))
        info.setStyleSheet("color: #888888;")
        layout.addWidget(info)

    def _launch_app(self, script):
        """Launch the selected application"""
        try:
            # Set up environment with current Python path
            env = os.environ.copy()
            script_dir = os.path.dirname(os.path.abspath(__file__))

            # Ensure PYTHONPATH includes the project directory so 'examples.poco_gui_common' imports work
            if 'PYTHONPATH' in env:
                env['PYTHONPATH'] = f"{script_dir}:{env['PYTHONPATH']}"
            else:
                env['PYTHONPATH'] = script_dir

            # Run from the project directory (parent of examples/) so imports work correctly
            subprocess.Popen([sys.executable, script], cwd=script_dir, env=env)
        except Exception as e:
            print(f"Error launching {script}: {e}")


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = LauncherGUI()
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
