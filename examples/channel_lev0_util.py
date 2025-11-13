#!/usr/bin/env python3
"""
Poco Channel Output Commands Utility GUI
=====================

GUI for sending low-level channel output commands (PLI, PWM, BIN) commands to Poco devices.
Focuses on direct channel control via PGN 61184 OUTPUTCH_xxx PIDs.
Also monitors channel status via OUTPUTCH_STATUS PID.

Dependencies:
    pip install python-can
    sudo apt install python3-pyqt5  # On Ubuntu/Debian

Run with:
    python3 channel_lev0_util.py
"""

import sys
from PyQt5.QtCore import Qt, QSettings, pyqtSignal
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QGridLayout, QLabel, QPushButton,
                             QSpinBox, QLineEdit, QGroupBox,
                             QTextEdit, QSlider, QTabWidget)
from PyQt5.QtGui import QFont
from examples.poco_gui_common import CANConnectionWidget, DARK_THEME_STYLESHEET, create_title_label, create_status_label, CommandRateLimiter
from poco_can.poco_can_interface import PocoCANInterfaceLevel0


class ChannelStatusWidget(QWidget):
    """
    Widget to display real-time status for a single output channel.
    Shows mode, output level, input voltage, and current.
    """

    def __init__(self, channel_num):
        super().__init__()
        self.channel_num = channel_num
        self.setFixedHeight(120)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # Channel title
        title = QLabel(f"Channel {self.channel_num}")
        title.setFont(QFont("Arial", 12, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # Status grid
        grid = QGridLayout()
        grid.setSpacing(4)

        # Mode
        grid.addWidget(QLabel("Mode:"), 0, 0)
        self.mode_label = QLabel("Unknown")
        self.mode_label.setStyleSheet("font-weight: bold; color: #cccccc;")
        grid.addWidget(self.mode_label, 0, 1)

        # Output Level
        grid.addWidget(QLabel("Output:"), 1, 0)
        self.output_label = QLabel("0%")
        self.output_label.setStyleSheet("font-weight: bold; color: #00ff00;")
        grid.addWidget(self.output_label, 1, 1)

        # Input Voltage (for fuse detection)
        grid.addWidget(QLabel("Input V:"), 2, 0)
        self.voltage_label = QLabel("0.0V")
        self.voltage_label.setStyleSheet("font-weight: bold; color: #ffaa00;")
        grid.addWidget(self.voltage_label, 2, 1)

        # Current
        grid.addWidget(QLabel("Current:"), 3, 0)
        self.current_label = QLabel("0.0A")
        self.current_label.setStyleSheet("font-weight: bold; color: #00aaff;")
        grid.addWidget(self.current_label, 3, 1)

        layout.addLayout(grid)

    def update_status(self, mode, output_level, input_voltage, current):
        """
        Update channel status display.

        Args:
            mode: 0=None/Off, 1=BIN, 2=PWM, 3=PLI
            output_level: 0-255 output level
            input_voltage: Input voltage in mV
            current: Current in mA
        """
        # Mode
        mode_names = {0: "OFF", 1: "BIN", 2: "PWM", 3: "PLI"}
        mode_str = mode_names.get(mode, f"UNK({mode})")
        self.mode_label.setText(mode_str)

        # Color mode label based on status
        if mode == 0:
            self.mode_label.setStyleSheet("font-weight: bold; color: #666666;")
        else:
            self.mode_label.setStyleSheet("font-weight: bold; color: #00ff00;")

        # Output Level
        if mode == 0:
            self.output_label.setText("0%")
            self.output_label.setStyleSheet("font-weight: bold; color: #666666;")
        elif mode == 1:  # BIN
            self.output_label.setText("ON" if output_level > 0 else "OFF")
            self.output_label.setStyleSheet("font-weight: bold; color: #00ff00;" if output_level > 0 else "font-weight: bold; color: #666666;")
        else:  # PWM or PLI
            percent = (output_level / 255.0) * 100
            self.output_label.setText(f"{percent:.0f}%")
            self.output_label.setStyleSheet("font-weight: bold; color: #00ff00;")

        # Input Voltage (highlight if low - indicates blown fuse)
        voltage_v = input_voltage / 1000.0
        self.voltage_label.setText(f"{voltage_v:.1f}V")
        if voltage_v < 8.0:  # Low voltage - possible blown fuse
            self.voltage_label.setStyleSheet("font-weight: bold; color: #ff4444; background-color: #440000;")
        else:
            self.voltage_label.setStyleSheet("font-weight: bold; color: #ffaa00;")

        # Current
        current_a = current / 1000.0
        self.current_label.setText(f"{current_a:.2f}A")
        if current_a > 10.0:  # High current warning
            self.current_label.setStyleSheet("font-weight: bold; color: #ffaa00; background-color: #443300;")
        else:
            self.current_label.setStyleSheet("font-weight: bold; color: #00aaff;")


class ChannelOutputCommandsGUI(QMainWindow):
    """GUI for low-level channel output command control and monitoring."""

    # Signal for thread-safe GUI updates
    channel_status_signal = pyqtSignal(int, int, int, int, int)  # channel, mode, output_level, input_voltage, current

    def __init__(self):
        super().__init__()
        self.poco = None
        self.channel_status_widgets = []
        self.settings = QSettings("Lumitec", "PocoChannelOutputCommands")

        self.setWindowTitle("Poco Channel Output Commands & Status")
        self.setGeometry(100, 100, 900, 800)

        # Enhanced stylesheet with better disabled state visibility
        enhanced_stylesheet = DARK_THEME_STYLESHEET + """
            QPushButton:disabled {
                background-color: #2a2a2a;
                color: #555555;
                border: 1px solid #3a3a3a;
            }
            QSpinBox:disabled {
                background-color: #2a2a2a;
                color: #555555;
                border: 1px solid #3a3a3a;
            }
            QLineEdit:disabled {
                background-color: #2a2a2a;
                color: #555555;
                border: 1px solid #3a3a3a;
            }
            QSlider:disabled {
                background-color: #2a2a2a;
            }
        """
        self.setStyleSheet(enhanced_stylesheet)

        # Connect signal for thread-safe GUI updates
        self.channel_status_signal.connect(self._update_channel_status_safe)

        # Rate limiter for PWM commands (delay to prevent flooding)
        self.pwm_rate_limiter = CommandRateLimiter()

        self._setup_ui()

    def _setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # Title
        title = create_title_label("Channel Output Commands")
        layout.addWidget(title)

        # CAN connection widget
        self.can_widget = CANConnectionWidget(settings_org="Lumitec", settings_app="PocoChannelOutputCommands")
        self.can_widget.connected.connect(self._on_connected)
        self.can_widget.disconnected.connect(self._on_disconnected)
        self.can_widget.connection_failed.connect(self._on_connection_failed)
        layout.addWidget(self.can_widget)

        # Channel Status Display (4 channels in a row)
        status_group = QGroupBox("Channel Status")
        status_layout = QHBoxLayout(status_group)
        status_layout.setSpacing(15)

        for i in range(1, 5):  # Channels 1-4
            channel_widget = ChannelStatusWidget(i)
            self.channel_status_widgets.append(channel_widget)
            status_layout.addWidget(channel_widget)

        layout.addWidget(status_group)

        # Tabs for different command types
        tabs = QTabWidget()

        # Tab 1: Binary Channel Control
        tabs.addTab(self._create_binary_tab(), "Binary (On/Off)")

        # Tab 2: PWM Channel Control
        tabs.addTab(self._create_pwm_tab(), "PWM (Brightness)")

        # Tab 3: Raw PLI Message
        tabs.addTab(self._create_raw_pli_tab(), "Raw PLI (Hex)")

        # Tab 4: PLI T2HSB
        tabs.addTab(self._create_t2hsb_tab(), "T2HSB (Hue/Sat/Bright)")

        # Tab 5: PLI T2RGB
        tabs.addTab(self._create_t2rgb_tab(), "T2RGB (RGB Color)")

        # Tab 6: PLI T2HS
        tabs.addTab(self._create_t2hs_tab(), "T2HS (Hue/Sat)")

        # Tab 7: PLI T2B
        tabs.addTab(self._create_t2b_tab(), "T2B (Brightness)")

        # Tab 8: PLI T2BD
        tabs.addTab(self._create_t2bd_tab(), "T2BD (Brightness Delta)")

        # Tab 9: PLI T2P
        tabs.addTab(self._create_t2p_tab(), "T2P (Pattern)")

        layout.addWidget(tabs)

        # Log
        log_label = QLabel("Command Log:")
        log_label.setFont(QFont("Arial", 12, QFont.Bold))
        layout.addWidget(log_label)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        layout.addWidget(self.log_text)

        # Status
        # Status
        self.status_label = create_status_label("Not connected")
        layout.addWidget(self.status_label)

        # Disable all controls initially (until CAN connection established)
        self._set_controls_enabled(False)

    def _set_controls_enabled(self, enabled):
        """Enable or disable all control widgets"""
        # Binary tab controls
        self.bin_channel_spin.setEnabled(enabled)
        self.bin_on_btn.setEnabled(enabled)
        self.bin_off_btn.setEnabled(enabled)

        # PWM tab controls
        self.pwm_channel_spin.setEnabled(enabled)
        self.pwm_slider.setEnabled(enabled)
        for btn in self.pwm_preset_btns:
            btn.setEnabled(enabled)

        # Raw PLI tab controls
        self.raw_channel_spin.setEnabled(enabled)
        self.raw_pli_edit.setEnabled(enabled)
        self.raw_pli_send_btn.setEnabled(enabled)
        for btn in self.raw_pli_example_btns:
            btn.setEnabled(enabled)

        # T2HSB tab controls
        self.t2hsb_channel_spin.setEnabled(enabled)
        self.t2hsb_clan_spin.setEnabled(enabled)
        self.t2hsb_transition_spin.setEnabled(enabled)
        self.t2hsb_hue_spin.setEnabled(enabled)
        self.t2hsb_sat_spin.setEnabled(enabled)
        self.t2hsb_bright_spin.setEnabled(enabled)
        self.t2hsb_send_btn.setEnabled(enabled)
        for btn in self.t2hsb_preset_btns:
            btn.setEnabled(enabled)


    def _on_connected(self, base_interface):
        """Called when CAN connection is established"""
        # Keep reference to base interface to stop its notifier on disconnect
        self.base_interface = base_interface

        # Create a Level 0 interface using the base connection
        self.poco = PocoCANInterfaceLevel0(
            interface=base_interface.interface,
            channel=base_interface.channel,
            bitrate=base_interface.bitrate,
            poco_address=base_interface.poco_address,
            source_address=base_interface.source_address
        )
        # Transfer the existing connection instead of creating a new one
        self.poco.bus = base_interface.bus
        self.poco.notifier = base_interface.notifier

        # Transfer enumeration data and callbacks from base interface
        self.poco.discovered_devices = base_interface.discovered_devices
        self.poco.enumeration_callbacks = base_interface.enumeration_callbacks

        # Update the connection widget to use our Level 0 interface for discovery
        self.can_widget.set_poco_interface(self.poco)

        # Set up status monitoring callback
        self.poco.add_channel_status_callback(self._on_channel_status_update)
        self.poco.start_listener()

        # Enable all controls now that we're connected
        self._set_controls_enabled(True)

        self.status_label.setText(f"Connected - Level 0 Protocol Active")
        self._log("Connected to CAN bus - Level 0 Protocol Active")

    def _on_disconnected(self):
        """Called when CAN connection is closed"""
        # Stop notifiers BEFORE the widget closes the bus
        if hasattr(self, 'base_interface') and self.base_interface:
            if self.base_interface.notifier:
                self.base_interface.notifier.stop()
                self.base_interface.notifier = None
            self.base_interface = None

        if self.poco:
            # Stop our notifier too
            if self.poco.notifier:
                self.poco.notifier.stop()
                self.poco.notifier = None
            # Remove callbacks
            self.poco.remove_channel_status_callback(self._on_channel_status_update)
            self.poco = None

        # Disable all controls when disconnected
        self._set_controls_enabled(False)

        self.status_label.setText("Not connected")
        self._log("Disconnected from CAN bus")

    def _on_connection_failed(self, error_msg):
        """Called when CAN connection fails"""
        self.status_label.setText(f"Connection failed: {error_msg}")
        self._log(f"ERROR: {error_msg}")

    def _on_channel_status_update(self, channel, mode, output_level, input_voltage_mv, current_ma):
        """Called when channel status is received from CAN bus (thread-safe)"""
        # Emit signal to handle GUI updates on main thread
        self.channel_status_signal.emit(channel, mode, output_level, input_voltage_mv, current_ma)

    def _update_channel_status_safe(self, channel, mode, output_level, input_voltage_mv, current_ma):
        """Thread-safe method to update channel status display"""
        if 1 <= channel <= 4:
            widget_index = channel - 1
            if widget_index < len(self.channel_status_widgets):
                self.channel_status_widgets[widget_index].update_status(mode, output_level, input_voltage_mv, current_ma)

            # Log status updates
            mode_names = {0: "OFF", 1: "BIN", 2: "PWM", 3: "PLI"}
            mode_str = mode_names.get(mode, f"UNK({mode})")
            self._log(f"Status Ch{channel}: {mode_str}, Level={output_level}, {input_voltage_mv/1000:.1f}V, {current_ma/1000:.2f}A")

    def _create_binary_tab(self):
        """Create tab for: Binary channel control"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)

        info = QLabel("OUTPUTCH_BIN - Binary on/off channel control")
        info.setWordWrap(True)
        layout.addWidget(info)

        # Channel selection
        channel_layout = QHBoxLayout()
        channel_layout.addWidget(QLabel("Output Channel (1-4):"))
        self.bin_channel_spin = QSpinBox()
        self.bin_channel_spin.setMinimum(1)
        self.bin_channel_spin.setMaximum(4)
        channel_layout.addWidget(self.bin_channel_spin)
        channel_layout.addStretch()
        layout.addLayout(channel_layout)

        # Control buttons
        btn_layout = QHBoxLayout()

        self.bin_on_btn = QPushButton("Turn ON")
        self.bin_on_btn.setMinimumHeight(40)
        self.bin_on_btn.clicked.connect(lambda: self._send_binary_command(1))
        btn_layout.addWidget(self.bin_on_btn)

        self.bin_off_btn = QPushButton("Turn OFF")
        self.bin_off_btn.setMinimumHeight(40)
        self.bin_off_btn.clicked.connect(lambda: self._send_binary_command(0))
        btn_layout.addWidget(self.bin_off_btn)

        layout.addLayout(btn_layout)
        layout.addStretch()

        return tab

    def _create_pwm_tab(self):
        """Create tab for PWM channel control"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)

        info = QLabel("OUTPUTCH_PWM - PWM duty cycle control (0-100%)")
        info.setWordWrap(True)
        layout.addWidget(info)

        # Channel selection
        channel_layout = QHBoxLayout()
        channel_layout.addWidget(QLabel("Output Channel (1-4):"))
        self.pwm_channel_spin = QSpinBox()
        self.pwm_channel_spin.setMinimum(1)
        self.pwm_channel_spin.setMaximum(4)
        channel_layout.addWidget(self.pwm_channel_spin)
        channel_layout.addStretch()
        layout.addLayout(channel_layout)

        # PWM duty cycle slider
        pwm_layout = QVBoxLayout()
        pwm_layout.addWidget(QLabel("Duty Cycle (%):"))

        slider_layout = QHBoxLayout()
        self.pwm_slider = QSlider(Qt.Horizontal)
        self.pwm_slider.setMinimum(0)
        self.pwm_slider.setMaximum(100)
        self.pwm_slider.setValue(50)
        self.pwm_slider.valueChanged.connect(self._update_pwm_label)
        self.pwm_slider.valueChanged.connect(self._send_pwm_command_rate_limited)
        slider_layout.addWidget(self.pwm_slider)

        self.pwm_value_label = QLabel("50%")
        self.pwm_value_label.setMinimumWidth(50)
        slider_layout.addWidget(self.pwm_value_label)

        pwm_layout.addLayout(slider_layout)
        layout.addLayout(pwm_layout)

        # Quick preset buttons
        preset_layout = QHBoxLayout()
        self.pwm_preset_btns = []
        for pct in [0, 25, 50, 75, 100]:
            btn = QPushButton(f"{pct}%")
            btn.clicked.connect(lambda checked, p=pct: self._set_pwm_preset(p))
            preset_layout.addWidget(btn)
            self.pwm_preset_btns.append(btn)
        layout.addLayout(preset_layout)

        # Info about automatic sending
        info_label = QLabel("💡 Commands sent automatically on slider changes (rate limited)")
        info_label.setStyleSheet("color: #888888; font-size: 10px; font-style: italic;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        layout.addStretch()

        return tab

    def _create_raw_pli_tab(self):
        """Create tab for Raw PLI message"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)

        info = QLabel("OUTPUTCH_PLI_RAW - Send raw 32-bit PLI message to output channel")
        info.setWordWrap(True)
        layout.addWidget(info)

        # Channel selection
        channel_layout = QHBoxLayout()
        channel_layout.addWidget(QLabel("Output Channel (1-4):"))
        self.raw_channel_spin = QSpinBox()
        self.raw_channel_spin.setMinimum(1)
        self.raw_channel_spin.setMaximum(4)
        channel_layout.addWidget(self.raw_channel_spin)
        channel_layout.addStretch()
        layout.addLayout(channel_layout)

        # Raw message input
        msg_layout = QVBoxLayout()
        msg_layout.addWidget(QLabel("PLI Message (32-bit hex):"))

        hex_layout = QHBoxLayout()
        hex_layout.addWidget(QLabel("0x"))
        self.raw_pli_edit = QLineEdit()
        self.raw_pli_edit.setPlaceholderText("00000000")
        self.raw_pli_edit.setMaxLength(8)
        self.raw_pli_edit.setText("00000000")
        # Only allow hex characters
        hex_layout.addWidget(self.raw_pli_edit)

        msg_layout.addLayout(hex_layout)
        layout.addLayout(msg_layout)

        # Send button
        self.raw_pli_send_btn = QPushButton("Send Raw PLI Message")
        self.raw_pli_send_btn.setMinimumHeight(40)
        self.raw_pli_send_btn.clicked.connect(self._send_raw_pli_command)
        layout.addWidget(self.raw_pli_send_btn)

        # Example commands
        examples_group = QGroupBox("Example Commands (clickable)")
        examples_layout = QVBoxLayout(examples_group)

        # These are properly encoded PLI messages with CRC and start bits
        # Values from components/lumitec-dev-pli-web/src/shared/poco.test.js
        examples = [
            ("All OFF (T2RGB)", "E0000808"),
            ("Red Full (T2HSB)", "FFE0080B"),
            ("White Full (T2HSB)", "FF000809"),
            ("Brightness Full (T2B)", "C45FE80A"),
            ("Brightness Half (T2B)", "C4500802"),
            ("Brightness OFF (T2B)", "C4400804"),
        ]

        self.raw_pli_example_btns = []
        for desc, value in examples:
            btn = QPushButton(f"{desc}: 0x{value}")
            btn.clicked.connect(lambda checked, v=value: self.raw_pli_edit.setText(v))
            examples_layout.addWidget(btn)
            self.raw_pli_example_btns.append(btn)

        layout.addWidget(examples_group)
        layout.addStretch()

        return tab

    def _create_t2hsb_tab(self):
        """Create tab for PLI T2HSB convenience command"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)

        info = QLabel("OUTPUTCH_PLI_T2HSB - Transition to HSB color (convenience wrapper)")
        info.setWordWrap(True)
        layout.addWidget(info)

        # Channel selection
        channel_layout = QHBoxLayout()
        channel_layout.addWidget(QLabel("Output Channel (1-4):"))
        self.t2hsb_channel_spin = QSpinBox()
        self.t2hsb_channel_spin.setMinimum(1)
        self.t2hsb_channel_spin.setMaximum(4)
        channel_layout.addWidget(self.t2hsb_channel_spin)
        channel_layout.addStretch()
        layout.addLayout(channel_layout)

        # PLI Protocol controls
        protocol_group = QGroupBox("PLI Protocol")
        protocol_layout = QGridLayout(protocol_group)

        # PLI Clan
        protocol_layout.addWidget(QLabel("PLI Clan (0-63):"), 0, 0)
        self.t2hsb_clan_spin = QSpinBox()
        self.t2hsb_clan_spin.setMinimum(0)
        self.t2hsb_clan_spin.setMaximum(63)
        self.t2hsb_clan_spin.setValue(0)
        protocol_layout.addWidget(self.t2hsb_clan_spin, 0, 1)
        protocol_layout.addWidget(QLabel("(6-bit PLI clan identifier)"), 0, 2)

        # Transition
        protocol_layout.addWidget(QLabel("Transition (0-7):"), 1, 0)
        self.t2hsb_transition_spin = QSpinBox()
        self.t2hsb_transition_spin.setMinimum(0)
        self.t2hsb_transition_spin.setMaximum(7)
        self.t2hsb_transition_spin.setValue(0)
        protocol_layout.addWidget(self.t2hsb_transition_spin, 1, 1)
        protocol_layout.addWidget(QLabel("(3-bit transition mode)"), 1, 2)

        layout.addWidget(protocol_group)

        # HSB controls
        hsb_group = QGroupBox("Color (HSB)")
        hsb_layout = QGridLayout(hsb_group)

        # Hue
        hsb_layout.addWidget(QLabel("Hue (0-255):"), 0, 0)
        self.t2hsb_hue_spin = QSpinBox()
        self.t2hsb_hue_spin.setMinimum(0)
        self.t2hsb_hue_spin.setMaximum(255)
        self.t2hsb_hue_spin.setValue(0)
        hsb_layout.addWidget(self.t2hsb_hue_spin, 0, 1)
        hsb_layout.addWidget(QLabel("(0=Red, 85=Green, 170=Blue)"), 0, 2)

        # Saturation
        hsb_layout.addWidget(QLabel("Saturation (0-255):"), 1, 0)
        self.t2hsb_sat_spin = QSpinBox()
        self.t2hsb_sat_spin.setMinimum(0)
        self.t2hsb_sat_spin.setMaximum(255)
        self.t2hsb_sat_spin.setValue(255)
        hsb_layout.addWidget(self.t2hsb_sat_spin, 1, 1)
        hsb_layout.addWidget(QLabel("(0=White, 255=Full color)"), 1, 2)

        # Brightness
        hsb_layout.addWidget(QLabel("Brightness (0-255):"), 2, 0)
        self.t2hsb_bright_spin = QSpinBox()
        self.t2hsb_bright_spin.setMinimum(0)
        self.t2hsb_bright_spin.setMaximum(255)
        self.t2hsb_bright_spin.setValue(255)
        hsb_layout.addWidget(self.t2hsb_bright_spin, 2, 1)
        hsb_layout.addWidget(QLabel("(0=Off, 255=Full)"), 2, 2)

        layout.addWidget(hsb_group)

        # Send button
        self.t2hsb_send_btn = QPushButton("Send T2HSB Command")
        self.t2hsb_send_btn.setMinimumHeight(40)
        self.t2hsb_send_btn.clicked.connect(self._send_t2hsb_command)
        layout.addWidget(self.t2hsb_send_btn)

        # Color presets
        presets_layout = QHBoxLayout()
        presets = [
            ("Red", 0, 255, 255),
            ("Green", 85, 255, 255),
            ("Blue", 170, 255, 255),
            ("White", 0, 0, 255),
        ]
        self.t2hsb_preset_btns = []
        for name, h, s, b in presets:
            btn = QPushButton(name)
            btn.clicked.connect(lambda checked, h=h, s=s, b=b: self._set_t2hsb_preset(h, s, b))
            presets_layout.addWidget(btn)
            self.t2hsb_preset_btns.append(btn)
        layout.addLayout(presets_layout)

        layout.addStretch()

        return tab

    def _create_t2rgb_tab(self):
        """Create tab for PLI T2RGB command (RGB color)"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)

        info = QLabel("OUTPUTCH_PLI_T2RGB - Set RGB color (5-bit per channel, 0-255 scaled)")
        info.setWordWrap(True)
        layout.addWidget(info)

        # Channel selection
        channel_layout = QHBoxLayout()
        channel_layout.addWidget(QLabel("Output Channel (1-4):"))
        self.t2rgb_channel_spin = QSpinBox()
        self.t2rgb_channel_spin.setMinimum(1)
        self.t2rgb_channel_spin.setMaximum(4)
        channel_layout.addWidget(self.t2rgb_channel_spin)
        channel_layout.addStretch()
        layout.addLayout(channel_layout)

        # PLI Protocol controls
        protocol_group = QGroupBox("PLI Protocol")
        protocol_layout = QGridLayout(protocol_group)

        protocol_layout.addWidget(QLabel("PLI Clan (0-63):"), 0, 0)
        self.t2rgb_clan_spin = QSpinBox()
        self.t2rgb_clan_spin.setMinimum(0)
        self.t2rgb_clan_spin.setMaximum(63)
        self.t2rgb_clan_spin.setValue(0)
        protocol_layout.addWidget(self.t2rgb_clan_spin, 0, 1)

        protocol_layout.addWidget(QLabel("Transition (0-7):"), 1, 0)
        self.t2rgb_transition_spin = QSpinBox()
        self.t2rgb_transition_spin.setMinimum(0)
        self.t2rgb_transition_spin.setMaximum(7)
        self.t2rgb_transition_spin.setValue(0)
        protocol_layout.addWidget(self.t2rgb_transition_spin, 1, 1)

        layout.addWidget(protocol_group)

        # RGB controls
        rgb_group = QGroupBox("RGB Color")
        rgb_layout = QGridLayout(rgb_group)

        rgb_layout.addWidget(QLabel("Red (0-255):"), 0, 0)
        self.t2rgb_red_spin = QSpinBox()
        self.t2rgb_red_spin.setMinimum(0)
        self.t2rgb_red_spin.setMaximum(255)
        self.t2rgb_red_spin.setValue(255)
        rgb_layout.addWidget(self.t2rgb_red_spin, 0, 1)

        rgb_layout.addWidget(QLabel("Green (0-255):"), 1, 0)
        self.t2rgb_green_spin = QSpinBox()
        self.t2rgb_green_spin.setMinimum(0)
        self.t2rgb_green_spin.setMaximum(255)
        self.t2rgb_green_spin.setValue(0)
        rgb_layout.addWidget(self.t2rgb_green_spin, 1, 1)

        rgb_layout.addWidget(QLabel("Blue (0-255):"), 2, 0)
        self.t2rgb_blue_spin = QSpinBox()
        self.t2rgb_blue_spin.setMinimum(0)
        self.t2rgb_blue_spin.setMaximum(255)
        self.t2rgb_blue_spin.setValue(0)
        rgb_layout.addWidget(self.t2rgb_blue_spin, 2, 1)

        layout.addWidget(rgb_group)

        # Send button
        self.t2rgb_send_btn = QPushButton("Send T2RGB Command")
        self.t2rgb_send_btn.setMinimumHeight(40)
        self.t2rgb_send_btn.clicked.connect(self._send_t2rgb_command)
        layout.addWidget(self.t2rgb_send_btn)

        # Color presets
        presets_layout = QHBoxLayout()
        presets = [
            ("Red", 255, 0, 0),
            ("Green", 0, 255, 0),
            ("Blue", 0, 0, 255),
            ("Yellow", 255, 255, 0),
            ("Cyan", 0, 255, 255),
            ("Magenta", 255, 0, 255),
            ("White", 255, 255, 255),
            ("Orange", 255, 131, 0),
        ]
        for name, r, g, b in presets:
            btn = QPushButton(name)
            btn.clicked.connect(lambda checked, r=r, g=g, b=b: self._set_t2rgb_preset(r, g, b))
            presets_layout.addWidget(btn)
        layout.addLayout(presets_layout)

        layout.addStretch()
        return tab

    def _create_t2hs_tab(self):
        """Create tab for PLI T2HS command (Hue/Sat only)"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)

        info = QLabel("OUTPUTCH_PLI_T2HS - Set Hue/Saturation (preserves brightness)")
        info.setWordWrap(True)
        layout.addWidget(info)

        # Channel selection
        channel_layout = QHBoxLayout()
        channel_layout.addWidget(QLabel("Output Channel (1-4):"))
        self.t2hs_channel_spin = QSpinBox()
        self.t2hs_channel_spin.setMinimum(1)
        self.t2hs_channel_spin.setMaximum(4)
        channel_layout.addWidget(self.t2hs_channel_spin)
        channel_layout.addStretch()
        layout.addLayout(channel_layout)

        # PLI Protocol controls
        protocol_group = QGroupBox("PLI Protocol")
        protocol_layout = QGridLayout(protocol_group)

        protocol_layout.addWidget(QLabel("PLI Clan (0-63):"), 0, 0)
        self.t2hs_clan_spin = QSpinBox()
        self.t2hs_clan_spin.setMinimum(0)
        self.t2hs_clan_spin.setMaximum(63)
        self.t2hs_clan_spin.setValue(0)
        protocol_layout.addWidget(self.t2hs_clan_spin, 0, 1)

        protocol_layout.addWidget(QLabel("Transition (0-7):"), 1, 0)
        self.t2hs_transition_spin = QSpinBox()
        self.t2hs_transition_spin.setMinimum(0)
        self.t2hs_transition_spin.setMaximum(7)
        self.t2hs_transition_spin.setValue(0)
        protocol_layout.addWidget(self.t2hs_transition_spin, 1, 1)

        layout.addWidget(protocol_group)

        # HS controls
        hs_group = QGroupBox("Hue/Saturation")
        hs_layout = QGridLayout(hs_group)

        hs_layout.addWidget(QLabel("Hue (0-255):"), 0, 0)
        self.t2hs_hue_spin = QSpinBox()
        self.t2hs_hue_spin.setMinimum(0)
        self.t2hs_hue_spin.setMaximum(255)
        self.t2hs_hue_spin.setValue(0)
        hs_layout.addWidget(self.t2hs_hue_spin, 0, 1)
        hs_layout.addWidget(QLabel("(0=Red, 85=Green, 170=Blue)"), 0, 2)

        hs_layout.addWidget(QLabel("Saturation (0-255):"), 1, 0)
        self.t2hs_sat_spin = QSpinBox()
        self.t2hs_sat_spin.setMinimum(0)
        self.t2hs_sat_spin.setMaximum(255)
        self.t2hs_sat_spin.setValue(255)
        hs_layout.addWidget(self.t2hs_sat_spin, 1, 1)
        hs_layout.addWidget(QLabel("(0=White, 255=Full color)"), 1, 2)

        layout.addWidget(hs_group)

        # Send button
        self.t2hs_send_btn = QPushButton("Send T2HS Command")
        self.t2hs_send_btn.setMinimumHeight(40)
        self.t2hs_send_btn.clicked.connect(self._send_t2hs_command)
        layout.addWidget(self.t2hs_send_btn)

        # Color presets
        presets_layout = QHBoxLayout()
        presets = [
            ("Red", 0, 255),
            ("Green", 85, 255),
            ("Blue", 170, 255),
            ("White", 0, 0),
        ]
        for name, h, s in presets:
            btn = QPushButton(name)
            btn.clicked.connect(lambda checked, h=h, s=s: self._set_t2hs_preset(h, s))
            presets_layout.addWidget(btn)
        layout.addLayout(presets_layout)

        layout.addStretch()
        return tab

    def _create_t2b_tab(self):
        """Create tab for PLI T2B command (Brightness only)"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)

        info = QLabel("OUTPUTCH_PLI_T2B - Set Brightness (preserves color)")
        info.setWordWrap(True)
        layout.addWidget(info)

        # Channel selection
        channel_layout = QHBoxLayout()
        channel_layout.addWidget(QLabel("Output Channel (1-4):"))
        self.t2b_channel_spin = QSpinBox()
        self.t2b_channel_spin.setMinimum(1)
        self.t2b_channel_spin.setMaximum(4)
        channel_layout.addWidget(self.t2b_channel_spin)
        channel_layout.addStretch()
        layout.addLayout(channel_layout)

        # PLI Protocol controls
        protocol_group = QGroupBox("PLI Protocol")
        protocol_layout = QGridLayout(protocol_group)

        protocol_layout.addWidget(QLabel("PLI Clan (0-63):"), 0, 0)
        self.t2b_clan_spin = QSpinBox()
        self.t2b_clan_spin.setMinimum(0)
        self.t2b_clan_spin.setMaximum(63)
        self.t2b_clan_spin.setValue(0)
        protocol_layout.addWidget(self.t2b_clan_spin, 0, 1)

        protocol_layout.addWidget(QLabel("Transition (0-7):"), 1, 0)
        self.t2b_transition_spin = QSpinBox()
        self.t2b_transition_spin.setMinimum(0)
        self.t2b_transition_spin.setMaximum(7)
        self.t2b_transition_spin.setValue(0)
        protocol_layout.addWidget(self.t2b_transition_spin, 1, 1)

        layout.addWidget(protocol_group)

        # Brightness control
        bright_group = QGroupBox("Brightness")
        bright_layout = QVBoxLayout(bright_group)

        slider_layout = QHBoxLayout()
        slider_layout.addWidget(QLabel("Brightness:"))
        self.t2b_slider = QSlider(Qt.Horizontal)
        self.t2b_slider.setMinimum(0)
        self.t2b_slider.setMaximum(255)
        self.t2b_slider.setValue(255)
        self.t2b_slider.setTickPosition(QSlider.TicksBelow)
        self.t2b_slider.setTickInterval(25)
        slider_layout.addWidget(self.t2b_slider)
        self.t2b_value_label = QLabel("255")
        self.t2b_value_label.setMinimumWidth(40)
        slider_layout.addWidget(self.t2b_value_label)
        bright_layout.addLayout(slider_layout)

        self.t2b_slider.valueChanged.connect(lambda v: self.t2b_value_label.setText(str(v)))

        layout.addWidget(bright_group)

        # Send button
        self.t2b_send_btn = QPushButton("Send T2B Command")
        self.t2b_send_btn.setMinimumHeight(40)
        self.t2b_send_btn.clicked.connect(self._send_t2b_command)
        layout.addWidget(self.t2b_send_btn)

        # Presets
        presets_layout = QHBoxLayout()
        presets = [("Off", 0), ("25%", 64), ("50%", 128), ("75%", 191), ("100%", 255)]
        for name, val in presets:
            btn = QPushButton(name)
            btn.clicked.connect(lambda checked, v=val: self.t2b_slider.setValue(v))
            presets_layout.addWidget(btn)
        layout.addLayout(presets_layout)

        layout.addStretch()
        return tab

    def _create_t2bd_tab(self):
        """Create tab for PLI T2BD command (Brightness Delta)"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)

        info = QLabel("OUTPUTCH_PLI_T2BD - Adjust Brightness by Delta (-127 to +127)")
        info.setWordWrap(True)
        layout.addWidget(info)

        # Channel selection
        channel_layout = QHBoxLayout()
        channel_layout.addWidget(QLabel("Output Channel (1-4):"))
        self.t2bd_channel_spin = QSpinBox()
        self.t2bd_channel_spin.setMinimum(1)
        self.t2bd_channel_spin.setMaximum(4)
        channel_layout.addWidget(self.t2bd_channel_spin)
        channel_layout.addStretch()
        layout.addLayout(channel_layout)

        # PLI Protocol controls
        protocol_group = QGroupBox("PLI Protocol")
        protocol_layout = QGridLayout(protocol_group)

        protocol_layout.addWidget(QLabel("PLI Clan (0-63):"), 0, 0)
        self.t2bd_clan_spin = QSpinBox()
        self.t2bd_clan_spin.setMinimum(0)
        self.t2bd_clan_spin.setMaximum(63)
        self.t2bd_clan_spin.setValue(0)
        protocol_layout.addWidget(self.t2bd_clan_spin, 0, 1)

        protocol_layout.addWidget(QLabel("Transition (0-7):"), 1, 0)
        self.t2bd_transition_spin = QSpinBox()
        self.t2bd_transition_spin.setMinimum(0)
        self.t2bd_transition_spin.setMaximum(7)
        self.t2bd_transition_spin.setValue(0)
        protocol_layout.addWidget(self.t2bd_transition_spin, 1, 1)

        layout.addWidget(protocol_group)

        # Delta control
        delta_group = QGroupBox("Brightness Delta")
        delta_layout = QGridLayout(delta_group)

        delta_layout.addWidget(QLabel("Delta (-127 to +127):"), 0, 0)
        self.t2bd_delta_spin = QSpinBox()
        self.t2bd_delta_spin.setMinimum(-127)
        self.t2bd_delta_spin.setMaximum(127)
        self.t2bd_delta_spin.setValue(10)
        delta_layout.addWidget(self.t2bd_delta_spin, 0, 1)
        delta_layout.addWidget(QLabel("(±0.79% per step)"), 0, 2)

        layout.addWidget(delta_group)

        # Send button
        self.t2bd_send_btn = QPushButton("Send T2BD Command")
        self.t2bd_send_btn.setMinimumHeight(40)
        self.t2bd_send_btn.clicked.connect(self._send_t2bd_command)
        layout.addWidget(self.t2bd_send_btn)

        # Presets
        presets_layout = QHBoxLayout()
        presets = [("-50", -50), ("-25", -25), ("-10", -10), ("+10", 10), ("+25", 25), ("+50", 50)]
        for name, val in presets:
            btn = QPushButton(name)
            btn.clicked.connect(lambda checked, v=val: self.t2bd_delta_spin.setValue(v))
            presets_layout.addWidget(btn)
        layout.addLayout(presets_layout)

        layout.addStretch()
        return tab

    def _create_t2p_tab(self):
        """Create tab for PLI T2P command (Pattern)"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)

        info = QLabel("OUTPUTCH_PLI_T2P - Start Pattern/Effect")
        info.setWordWrap(True)
        layout.addWidget(info)

        # Channel selection
        channel_layout = QHBoxLayout()
        channel_layout.addWidget(QLabel("Output Channel (1-4):"))
        self.t2p_channel_spin = QSpinBox()
        self.t2p_channel_spin.setMinimum(1)
        self.t2p_channel_spin.setMaximum(4)
        channel_layout.addWidget(self.t2p_channel_spin)
        channel_layout.addStretch()
        layout.addLayout(channel_layout)

        # PLI Protocol controls
        protocol_group = QGroupBox("PLI Protocol")
        protocol_layout = QGridLayout(protocol_group)

        protocol_layout.addWidget(QLabel("PLI Clan (0-63):"), 0, 0)
        self.t2p_clan_spin = QSpinBox()
        self.t2p_clan_spin.setMinimum(0)
        self.t2p_clan_spin.setMaximum(63)
        self.t2p_clan_spin.setValue(0)
        protocol_layout.addWidget(self.t2p_clan_spin, 0, 1)

        protocol_layout.addWidget(QLabel("Transition (0-7):"), 1, 0)
        self.t2p_transition_spin = QSpinBox()
        self.t2p_transition_spin.setMinimum(0)
        self.t2p_transition_spin.setMaximum(7)
        self.t2p_transition_spin.setValue(0)
        protocol_layout.addWidget(self.t2p_transition_spin, 1, 1)

        layout.addWidget(protocol_group)

        # Pattern selection
        pattern_group = QGroupBox("Pattern")
        pattern_layout = QGridLayout(pattern_group)

        pattern_layout.addWidget(QLabel("Pattern ID (0-255):"), 0, 0)
        self.t2p_pattern_spin = QSpinBox()
        self.t2p_pattern_spin.setMinimum(0)
        self.t2p_pattern_spin.setMaximum(255)
        self.t2p_pattern_spin.setValue(4)
        pattern_layout.addWidget(self.t2p_pattern_spin, 0, 1)

        layout.addWidget(pattern_group)

        # Send button
        self.t2p_send_btn = QPushButton("Send T2P Command")
        self.t2p_send_btn.setMinimumHeight(40)
        self.t2p_send_btn.clicked.connect(self._send_t2p_command)
        layout.addWidget(self.t2p_send_btn)

        # Pattern presets
        presets_layout = QHBoxLayout()
        presets = [
            ("Color Cycle", 4),
            ("Cross Fade", 5),
        ]
        for name, pid in presets:
            btn = QPushButton(name)
            btn.clicked.connect(lambda checked, p=pid: self.t2p_pattern_spin.setValue(p))
            presets_layout.addWidget(btn)
        layout.addLayout(presets_layout)

        layout.addStretch()
        return tab

    def _update_pwm_label(self, value):
        self.pwm_value_label.setText(f"{value}%")

    def _set_t2hsb_preset(self, h, s, b):
        # Set reasonable defaults for clan and transition when using presets
        self.t2hsb_clan_spin.setValue(0)
        self.t2hsb_transition_spin.setValue(0)
        self.t2hsb_hue_spin.setValue(h)
        self.t2hsb_sat_spin.setValue(s)
        self.t2hsb_bright_spin.setValue(b)

    def _log(self, message):
        """Add message to log"""
        self.log_text.append(message)

    def _send_binary_command(self, state):
        """Send Binary channel control"""
        if not self.poco:
            self.status_label.setText("Not connected")
            return

        channel = self.bin_channel_spin.value()
        state_name = "ON" if state else "OFF"

        try:
            self.poco.send_binary_channel(channel, state)
            self._log(f"Channel {channel} -> {state_name}")
            self.status_label.setText(f"Channel {channel}: Binary {state_name}")
        except Exception as e:
            self._log(f"ERROR: {str(e)}")
            self.status_label.setText(f"Error: {str(e)}")

    def _send_pwm_command_rate_limited(self):
        """Send PWM output command through rate limiter"""
        if not self.poco:
            return

        try:
            channel = self.pwm_channel_spin.value()
            duty_cycle_percent = self.pwm_slider.value()

            # Use rate limiter to prevent CAN bus flooding
            self.pwm_rate_limiter.queue_command(
                lambda: self._execute_pwm_command(channel, duty_cycle_percent)
            )
        except Exception as e:
            self._log(f"ERROR queueing PWM: {str(e)}")

    def _execute_pwm_command(self, channel, duty_cycle_percent):
        """Actually execute the PWM command (called by rate limiter)"""
        try:
            # Convert percentage to 0-255 range for protocol
            duty_cycle_raw = int((duty_cycle_percent / 100.0) * 255)

            self.poco.send_pwm_channel(channel, duty_cycle_raw)
            self._log(f"Channel {channel} -> PWM {duty_cycle_percent}%")
            self.status_label.setText(f"Channel {channel}: PWM {duty_cycle_percent}%")
        except Exception as e:
            self._log(f"ERROR: {str(e)}")
            self.status_label.setText(f"Error: {str(e)}")

    def _set_pwm_preset(self, percent):
        """Set PWM slider to preset value and send command"""
        self.pwm_slider.setValue(percent)
        # Command will be sent automatically via valueChanged signal

    def _send_raw_pli_command(self):
        """Send Raw PLI message"""
        if not self.poco:
            self.status_label.setText("Not connected")
            return

        channel = self.raw_channel_spin.value()
        hex_str = self.raw_pli_edit.text().strip()

        try:
            # Convert hex string to integer
            pli_message = int(hex_str, 16)

            self.poco.send_pli_raw(channel, pli_message)
            self._log(f"Channel {channel} -> Raw PLI 0x{hex_str}")
            self.status_label.setText(f"Sent raw PLI message to channel {channel}")
        except ValueError:
            self._log(f"ERROR: Invalid hex value: {hex_str}")
            self.status_label.setText("Error: Invalid hex value")
        except Exception as e:
            self._log(f"ERROR: {str(e)}")
            self.status_label.setText(f"Error: {str(e)}")

    def _send_t2hsb_command(self):
        """Send T2HSB command"""
        if not self.poco:
            self.status_label.setText("Not connected")
            return

        channel = self.t2hsb_channel_spin.value()
        clan = self.t2hsb_clan_spin.value()
        transition = self.t2hsb_transition_spin.value()
        hue = self.t2hsb_hue_spin.value()
        sat = self.t2hsb_sat_spin.value()
        bright = self.t2hsb_bright_spin.value()

        try:
            self.poco.send_pli_t2hsb(channel, hue, sat, bright, clan, transition)
            self._log(f"Channel {channel} -> T2HSB(Clan={clan}, Trans={transition}, H={hue}, S={sat}, B={bright})")
            self.status_label.setText(f"Channel {channel}: T2HSB command sent")
        except Exception as e:
            self._log(f"ERROR: {str(e)}")
            self.status_label.setText(f"Error: {str(e)}")

    def _send_t2rgb_command(self):
        """Send T2RGB command"""
        if not self.poco:
            self.status_label.setText("Not connected")
            return

        channel = self.t2rgb_channel_spin.value()
        clan = self.t2rgb_clan_spin.value()
        transition = self.t2rgb_transition_spin.value()
        red = self.t2rgb_red_spin.value()
        green = self.t2rgb_green_spin.value()
        blue = self.t2rgb_blue_spin.value()

        try:
            self.poco.send_pli_t2rgb(channel, red, green, blue, clan, transition)
            self._log(f"Channel {channel} -> T2RGB(Clan={clan}, Trans={transition}, R={red}, G={green}, B={blue})")
            self.status_label.setText(f"Channel {channel}: T2RGB command sent")
        except Exception as e:
            self._log(f"ERROR: {str(e)}")
            self.status_label.setText(f"Error: {str(e)}")

    def _set_t2rgb_preset(self, r, g, b):
        """Set RGB color preset"""
        self.t2rgb_red_spin.setValue(r)
        self.t2rgb_green_spin.setValue(g)
        self.t2rgb_blue_spin.setValue(b)

    def _send_t2hs_command(self):
        """Send T2HS command"""
        if not self.poco:
            self.status_label.setText("Not connected")
            return

        channel = self.t2hs_channel_spin.value()
        clan = self.t2hs_clan_spin.value()
        transition = self.t2hs_transition_spin.value()
        hue = self.t2hs_hue_spin.value()
        sat = self.t2hs_sat_spin.value()

        try:
            self.poco.send_pli_t2hs(channel, hue, sat, clan, transition)
            self._log(f"Channel {channel} -> T2HS(Clan={clan}, Trans={transition}, H={hue}, S={sat})")
            self.status_label.setText(f"Channel {channel}: T2HS command sent")
        except Exception as e:
            self._log(f"ERROR: {str(e)}")
            self.status_label.setText(f"Error: {str(e)}")

    def _set_t2hs_preset(self, h, s):
        """Set hue/sat preset"""
        self.t2hs_hue_spin.setValue(h)
        self.t2hs_sat_spin.setValue(s)

    def _send_t2b_command(self):
        """Send T2B command"""
        if not self.poco:
            self.status_label.setText("Not connected")
            return

        channel = self.t2b_channel_spin.value()
        clan = self.t2b_clan_spin.value()
        transition = self.t2b_transition_spin.value()
        brightness = self.t2b_slider.value()

        try:
            self.poco.send_pli_t2b(channel, brightness, clan, transition)
            self._log(f"Channel {channel} -> T2B(Clan={clan}, Trans={transition}, Brightness={brightness})")
            self.status_label.setText(f"Channel {channel}: T2B command sent")
        except Exception as e:
            self._log(f"ERROR: {str(e)}")
            self.status_label.setText(f"Error: {str(e)}")

    def _send_t2bd_command(self):
        """Send T2BD command"""
        if not self.poco:
            self.status_label.setText("Not connected")
            return

        channel = self.t2bd_channel_spin.value()
        clan = self.t2bd_clan_spin.value()
        transition = self.t2bd_transition_spin.value()
        delta = self.t2bd_delta_spin.value()

        try:
            self.poco.send_pli_t2bd(channel, delta, clan, transition)
            self._log(f"Channel {channel} -> T2BD(Clan={clan}, Trans={transition}, Delta={delta})")
            self.status_label.setText(f"Channel {channel}: T2BD command sent")
        except Exception as e:
            self._log(f"ERROR: {str(e)}")
            self.status_label.setText(f"Error: {str(e)}")

    def _send_t2p_command(self):
        """Send T2P command"""
        if not self.poco:
            self.status_label.setText("Not connected")
            return

        channel = self.t2p_channel_spin.value()
        clan = self.t2p_clan_spin.value()
        transition = self.t2p_transition_spin.value()
        pattern = self.t2p_pattern_spin.value()

        try:
            self.poco.send_pli_t2p(channel, pattern, clan, transition)
            self._log(f"Channel {channel} -> T2P(Clan={clan}, Trans={transition}, Pattern={pattern})")
            self.status_label.setText(f"Channel {channel}: T2P command sent")
        except Exception as e:
            self._log(f"ERROR: {str(e)}")
            self.status_label.setText(f"Error: {str(e)}")

    def closeEvent(self, event):
        """Clean up CAN connection when window closes"""
        if self.poco:
            self.poco.remove_channel_status_callback(self._on_channel_status_update)
        self.can_widget.cleanup()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = ChannelOutputCommandsGUI()
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
