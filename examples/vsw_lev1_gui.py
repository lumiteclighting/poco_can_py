#!/usr/bin/env python3
"""
Poco Binary Switches GUI
=========================

GUI for controlling and monitoring Lumitec Poco Virtual Switches using N2K binary switch protocol.
Focuses on PGN 127501 (Binary Switch Status) and PGN 127502 (Binary Switch Control).

Dependencies:
    pip install python-can
    sudo apt install python3-pyqt5  # On Ubuntu/Debian

Run with:
    python3 extsw_lev1_gui.py
"""

import sys
from PyQt5.QtCore import Qt, pyqtSignal, QSettings
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QGridLayout, QLabel, QPushButton,
                             QFrame, QSpinBox, QGroupBox)
from PyQt5.QtGui import QPainter, QPen, QBrush, QColor, QFont

from examples.poco_gui_common import CANConnectionWidget, DARK_THEME_STYLESHEET, create_title_label, create_status_label
from poco_can.poco_can_interface import PocoCANInterfaceLevel1


class BinaryLEDIndicator(QWidget):
    """
    Round LED indicator for binary switch status.
    Shows red/green/gray for off/on/unavailable states.
    Clickable to toggle the switch state.
    """

    # State constants
    OFF = 0
    ON = 1
    NA = 3

    clicked = pyqtSignal(int, int)  # Emits (switch_id, new_state) when clicked

    def __init__(self, switch_id=0):
        super().__init__()
        self.switch_id = switch_id
        self.state = 3  # 0=Off, 1=On, 3=N/A
        self.setFixedSize(30, 30)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(f"Binary Switch {self.switch_id + 1}: N/A\nClick to toggle")

    def set_state(self, state):
        """Set LED state: 0=Off, 1=On, 3=N/A"""
        self.state = state

        if state == 0:
            status = "OFF"
        elif state == 1:
            status = "ON"
        else:
            status = "N/A"

        self.setToolTip(f"Binary Switch {self.switch_id + 1}: {status}\nClick to toggle")
        self.update()

    def mousePressEvent(self, event):
        """Handle mouse clicks to toggle switch state"""
        if event.button() == Qt.LeftButton:
            if self.state in (self.OFF, self.ON):
                new_state = self.ON if self.state == self.OFF else self.OFF
                self.clicked.emit(self.switch_id, new_state)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect()
        center = rect.center()
        radius = min(rect.width(), rect.height()) // 2 - 2

        # If widget is disabled, draw with very low opacity
        if not self.isEnabled():
            led_color = QColor(60, 60, 60)  # Very dark gray
            border_color = QColor(40, 40, 40)
        # Choose color based on state
        elif self.state == 0:  # Off
            led_color = QColor(200, 60, 60)  # Red
            border_color = QColor(150, 40, 40)
        elif self.state == 1:  # On
            led_color = QColor(60, 200, 60)  # Green
            border_color = QColor(40, 150, 40)
        else:  # N/A
            led_color = QColor(100, 100, 100)  # Gray
            border_color = QColor(70, 70, 70)

        # Draw LED
        painter.setPen(QPen(border_color, 1))
        painter.setBrush(QBrush(led_color))
        painter.drawEllipse(center.x() - radius, center.y() - radius, radius * 2, radius * 2)

        # Add highlight for 3D effect (only when enabled and not N/A)
        if self.isEnabled() and self.state != 3:
            highlight = QColor(255, 255, 255, 100)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(highlight))
            highlight_radius = radius // 3
            highlight_x = center.x() - radius // 2
            highlight_y = center.y() - radius // 2
            painter.drawEllipse(highlight_x, highlight_y, highlight_radius, highlight_radius)


class BinarySwitchesGUI(QMainWindow):
    """GUI for binary switch control and monitoring."""

    # Signal for thread-safe GUI updates
    device_state_signal = pyqtSignal(int, list)  # bank, switch_states

    def __init__(self):
        super().__init__()
        self.binary_leds = []
        self.current_bank = 0  # Default to bank 0
        self.settings = QSettings("Lumitec", "PocoBinarySwitches")

        self.setWindowTitle("Poco Binary Switches")
        self.setGeometry(100, 100, 700, 600)

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
            QGroupBox:disabled {
                color: #555555;
            }
        """
        self.setStyleSheet(enhanced_stylesheet)

        # Connect signal for thread-safe GUI updates
        self.device_state_signal.connect(self._update_binary_indicators_safe)

        self._setup_ui()
        self._load_bank_setting()

    def _setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # Title
        title = create_title_label("Binary Switch Control & Monitor")
        layout.addWidget(title)

        # CAN connection widget
        self.can_widget = CANConnectionWidget(settings_org="Lumitec", settings_app="PocoBinarySwitches")
        self.can_widget.connected.connect(self._on_connected)
        self.can_widget.disconnected.connect(self._on_disconnected)
        self.can_widget.connection_failed.connect(self._on_connection_failed)
        layout.addWidget(self.can_widget)

        # Bank selection (separate from CAN connection)
        bank_frame = QFrame()
        bank_frame.setFrameStyle(QFrame.StyledPanel)
        bank_layout = QHBoxLayout(bank_frame)

        bank_layout.addWidget(QLabel("Bank Number:"))
        self.bank_spin = QSpinBox()
        self.bank_spin.setMinimum(0)
        self.bank_spin.setMaximum(255)
        self.bank_spin.setToolTip("Binary Switch Bank (0-255)")
        self.bank_spin.valueChanged.connect(self._on_bank_changed)
        self.bank_spin.setValue(0)  # Set value AFTER connecting signal so current_bank gets updated
        bank_layout.addWidget(self.bank_spin)

        bank_layout.addStretch()

        bank_info = QLabel("Controls which switch bank to monitor and control")
        bank_info.setStyleSheet("color: #888888; font-size: 10px;")
        bank_layout.addWidget(bank_info)

        layout.addWidget(bank_frame)

        # Binary switch indicators (28 switches in 4 rows of 7)
        switches_group = QGroupBox("Binary Switches (Click to Toggle)")
        switches_layout = QGridLayout(switches_group)
        switches_layout.setSpacing(15)
        switches_layout.setHorizontalSpacing(25)

        for i in range(28):
            row = i // 7
            col = i % 7

            led_container = QWidget()
            led_container_layout = QVBoxLayout(led_container)
            led_container_layout.setContentsMargins(0, 0, 0, 0)
            led_container_layout.setSpacing(3)

            led = BinaryLEDIndicator(i)
            led.clicked.connect(self._on_binary_led_clicked)
            self.binary_leds.append(led)

            led_container_layout.addWidget(led, 0, Qt.AlignCenter)

            led_label = QLabel(str(i + 1))
            led_label.setAlignment(Qt.AlignCenter)
            led_label.setFont(QFont("Arial", 9))
            led_container_layout.addWidget(led_label)

            switches_layout.addWidget(led_container, row, col)

        layout.addWidget(switches_group)

        # Batch control
        batch_group = QGroupBox("Batch Operations")
        batch_layout = QHBoxLayout(batch_group)

        self.all_on_btn = QPushButton("All ON")
        self.all_on_btn.clicked.connect(lambda: self._batch_control(1))
        batch_layout.addWidget(self.all_on_btn)

        self.all_off_btn = QPushButton("All OFF")
        self.all_off_btn.clicked.connect(lambda: self._batch_control(0))
        batch_layout.addWidget(self.all_off_btn)

        batch_layout.addWidget(QLabel("Range:"))
        self.range_start_spin = QSpinBox()
        self.range_start_spin.setMinimum(1)
        self.range_start_spin.setMaximum(28)
        self.range_start_spin.setValue(1)
        batch_layout.addWidget(self.range_start_spin)

        batch_layout.addWidget(QLabel("to"))
        self.range_end_spin = QSpinBox()
        self.range_end_spin.setMinimum(1)
        self.range_end_spin.setMaximum(28)
        self.range_end_spin.setValue(10)
        batch_layout.addWidget(self.range_end_spin)

        self.range_on_btn = QPushButton("Range ON")
        self.range_on_btn.clicked.connect(lambda: self._range_control(1))
        batch_layout.addWidget(self.range_on_btn)

        self.range_off_btn = QPushButton("Range OFF")
        self.range_off_btn.clicked.connect(lambda: self._range_control(0))
        batch_layout.addWidget(self.range_off_btn)

        layout.addWidget(batch_group)

        # Disable all controls initially (until CAN connection established)
        self.bank_spin.setEnabled(False)
        for led in self.binary_leds:
            led.setEnabled(False)
        self.all_on_btn.setEnabled(False)
        self.all_off_btn.setEnabled(False)
        self.range_on_btn.setEnabled(False)
        self.range_off_btn.setEnabled(False)
        self.range_start_spin.setEnabled(False)
        self.range_end_spin.setEnabled(False)

        # Status
        # Status
        self.status_label = create_status_label("Not connected")
        layout.addWidget(self.status_label)

    def _load_bank_setting(self):
        """Load saved bank setting"""
        saved_bank = self.settings.value("bank", 0, type=int)  # Default to bank 0
        self.bank_spin.setValue(saved_bank)

    def _on_connected(self, base_interface):
        """Called when CAN connection is established"""
        # Create a Level 1 interface using the base connection
        self.poco_level1 = PocoCANInterfaceLevel1(
            interface=base_interface.interface,
            channel=base_interface.channel,
            bitrate=base_interface.bitrate,
            poco_address=base_interface.poco_address,
            source_address=base_interface.source_address
        )
        # Transfer the existing connection instead of creating a new one
        self.poco_level1.bus = base_interface.bus
        self.poco_level1.notifier = base_interface.notifier

        # Transfer enumeration data and callbacks from base interface
        self.poco_level1.discovered_devices = base_interface.discovered_devices
        self.poco_level1.enumeration_callbacks = base_interface.enumeration_callbacks

        # Update the connection widget to use our Level 1 interface for discovery
        self.can_widget.set_poco_interface(self.poco_level1)

        self.poco_level1.add_binary_callback(self._update_binary_indicators)
        self.poco_level1.start_listener()

        # Enable all controls now that we're connected
        self.bank_spin.setEnabled(True)
        for led in self.binary_leds:
            led.setEnabled(True)
        self.all_on_btn.setEnabled(True)
        self.all_off_btn.setEnabled(True)
        self.range_on_btn.setEnabled(True)
        self.range_off_btn.setEnabled(True)
        self.range_start_spin.setEnabled(True)
        self.range_end_spin.setEnabled(True)

        self.status_label.setText(f"Connected to {base_interface.interface}:{base_interface.channel} - Monitoring Bank {self.current_bank}")

    def _on_disconnected(self):
        """Called when CAN connection is closed"""
        if hasattr(self, 'poco_level1') and self.poco_level1:
            self.poco_level1.remove_binary_callback(self._update_binary_indicators)
            self.poco_level1 = None

        # Disable all controls when disconnected
        self.bank_spin.setEnabled(False)
        for led in self.binary_leds:
            led.setEnabled(False)
        self.all_on_btn.setEnabled(False)
        self.all_off_btn.setEnabled(False)
        self.range_on_btn.setEnabled(False)
        self.range_off_btn.setEnabled(False)
        self.range_start_spin.setEnabled(False)
        self.range_end_spin.setEnabled(False)

        self.status_label.setText("Not connected")

    def _on_connection_failed(self, error_msg):
        """Called when CAN connection fails"""
        self.status_label.setText(f"Connection failed: {error_msg}")

    def _on_bank_changed(self, value):
        self.current_bank = value
        self.settings.setValue("bank", value)
        if self.can_widget.is_connected():
            self.status_label.setText(f"Monitoring Bank {self.current_bank}")

    def _update_binary_indicators(self, bank, switch_states):
        """Update LED indicators when receiving binary switch status from CAN bus (thread-safe)"""
        # Emit signal to handle GUI updates on main thread
        self.device_state_signal.emit(bank, switch_states)

    def _update_binary_indicators_safe(self, bank, switch_states):
        """Thread-safe GUI update method - runs on main thread"""
        if bank != self.current_bank:
            return  # Ignore updates for other banks

        for i in range(min(len(self.binary_leds), len(switch_states))):
            state = switch_states[i]
            if state == 0:
                self.binary_leds[i].set_state(BinaryLEDIndicator.OFF)
            elif state == 1:
                self.binary_leds[i].set_state(BinaryLEDIndicator.ON)
            else:
                self.binary_leds[i].set_state(BinaryLEDIndicator.NA)

        on_count = sum(1 for state in switch_states if state == 1)
        off_count = sum(1 for state in switch_states if state == 0)
        self.status_label.setText(f"Bank {bank}: {on_count} ON, {off_count} OFF")

    def _on_binary_led_clicked(self, switch_id, new_state):
        """Handle binary LED indicator clicks"""
        if not hasattr(self, 'poco_level1') or not self.poco_level1:
            self.status_label.setText("Not connected - cannot control switches")
            return

        try:
            # Build switch states array - set clicked switch, rest to "No Change"
            switch_states = [3] * 28
            switch_states[switch_id] = new_state

            self.poco_level1.send_binary_switch_control(self.current_bank, switch_states)
            self.binary_leds[switch_id].set_state(new_state)

            state_name = "ON" if new_state == 1 else "OFF"
            self.status_label.setText(f"Switch {switch_id + 1}: Set to {state_name}")

        except Exception as e:
            self.status_label.setText(f"Error: {str(e)}")

    def _batch_control(self, state):
        """Control all switches"""
        if not hasattr(self, 'poco_level1') or not self.poco_level1:
            return

        try:
            switch_states = [state] * 28
            self.poco_level1.send_binary_switch_control(self.current_bank, switch_states)

            for led in self.binary_leds:
                led.set_state(state)

            state_name = "ON" if state == 1 else "OFF"
            self.status_label.setText(f"All switches set to {state_name}")

        except Exception as e:
            self.status_label.setText(f"Error: {str(e)}")

    def _range_control(self, state):
        """Control a range of switches"""
        if not hasattr(self, 'poco_level1') or not self.poco_level1:
            return

        try:
            start = self.range_start_spin.value() - 1  # Convert to 0-based
            end = self.range_end_spin.value()  # Inclusive range

            switch_states = [3] * 28  # All "No Change"
            for i in range(start, end):
                if i < 28:
                    switch_states[i] = state

            self.poco_level1.send_binary_switch_control(self.current_bank, switch_states)

            for i in range(start, end):
                if i < len(self.binary_leds):
                    self.binary_leds[i].set_state(state)

            state_name = "ON" if state == 1 else "OFF"
            self.status_label.setText(f"Switches {start+1}-{end} set to {state_name}")

        except Exception as e:
            self.status_label.setText(f"Error: {str(e)}")

    def closeEvent(self, event):
        """Clean up CAN connection when window closes"""
        if hasattr(self, 'poco_level1') and self.poco_level1:
            self.poco_level1.remove_binary_callback(self._update_binary_indicators)
        self.can_widget.cleanup()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = BinarySwitchesGUI()
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
