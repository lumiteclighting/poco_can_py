#!/usr/bin/env python3
"""
Poco External Switches Level 2 Example GUI
==========================

GUI for controlling Lumitec Poco devices using ExtSw CAN protocol Level 2.

Dependencies:
    pip install python-can
    sudo apt install python3-pyqt5  # On Ubuntu/Debian

Run with:
    python3 extsw_lev2_gui.py
"""

import sys
import math
import time
import os
import colorsys
from PyQt5.QtCore import Qt, QTimer, QPoint, QRect, pyqtSignal
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QGridLayout, QLabel, QPushButton,
                             QDialog, QFrame, QComboBox, QSlider, QSpinBox)
from PyQt5.QtGui import QPainter, QPen, QBrush, QColor, QFont, QPixmap, QImage
from examples.poco_gui_common import CANConnectionWidget, DARK_THEME_STYLESHEET, create_title_label, create_status_label, CommandRateLimiter
from poco_can.poco_can_interface import PocoCANInterfaceLevel2

POCOFX_DATA = [
    {'name': 'None (Solid Color)', 'FxId': 0},
    {'name': 'Color Cycle', 'FxId': 4},
    {'name': 'Cross Fade', 'FxId': 5},
    {'name': 'White Caps', 'FxId': 128},
    {'name': 'Light Chop', 'FxId': 129},
    {'name': 'High Seas', 'FxId': 130},
    {'name': 'No Wake', 'FxId': 131},
    {'name': 'Cyclonic', 'FxId': 132},
    {'name': 'Wind Gusts', 'FxId': 133}
]

class CircularSwitch(QWidget):
    """
    Custom circular switch widget that mimics the Poco app interface.
    Features a power button icon in the center with a colored ring around it.
    """
    clicked = pyqtSignal()
    long_pressed = pyqtSignal()

    def __init__(self, switch_id=0, label="Switch"):
        super().__init__()
        self.switch_id = switch_id
        self.label = label
        self.is_on = False
        self.hue = 0     # Hue doesn't matter for white light
        self.saturation = 0   # Zero saturation = white light
        self.brightness = 100   # Full brightness for default white
        self.is_synced = True  # Whether GUI state matches device state

        # Long press detection
        self.press_timer = QTimer()
        self.press_timer.setSingleShot(True)
        self.press_timer.timeout.connect(self.long_pressed.emit)

        # Sync timeout - clears red dot if no device response
        self.sync_timer = QTimer()
        self.sync_timer.setSingleShot(True)
        self.sync_timer.timeout.connect(self._sync_timeout)

        self.setMinimumSize(120, 140)  # Width, Height (extra for label)
        self.setMaximumSize(150, 170)

        # Initialize tooltip
        self._update_tooltip()

    def _update_tooltip(self):
        """Update the tooltip with current state information"""
        state_text = "ON" if self.is_on else "OFF"
        sync_text = "✓" if self.is_synced else "⚠"

        tooltip_html = (
            f"<b>{self.label}</b> - {state_text} {sync_text}<br/>"
            f"<i>Interactions:</i><br/>"
            f"• <b>Click</b> to toggle on/off<br/>"
            f"• <b>Hold</b> to open color controls"
        )

        self.setToolTip(tooltip_html)

    def set_state(self, on_state, synced=True):
        """Set the switch on/off state"""
        self.is_on = on_state
        self.is_synced = synced
        if not synced:
            # Start timeout to auto-sync if no device response
            self.sync_timer.start(2000)  # 2 second timeout
        else:
            self.sync_timer.stop()
        self._update_tooltip()
        self.update()

    def _sync_timeout(self):
        """Called when no device response received - assume command worked"""
        self.is_synced = True
        self.update()

    def set_color(self, hue, saturation=100, brightness=100, synced=True):
        """Set the ring color using HSV values"""
        self.hue = int(hue) % 360
        self.saturation = max(0, min(100, saturation))
        self.brightness = max(0, min(100, brightness))
        self.is_synced = synced
        self._update_tooltip()
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.press_timer.start(500)  # 500ms for long press

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.press_timer.isActive():
                self.press_timer.stop()
                self.clicked.emit()  # Short click

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect()

        # Calculate available space for switch (leave room for label)
        available_height = rect.height() - 35  # Reserve 35px for label
        available_width = rect.width() - 10   # Small margin
        switch_size = min(available_width, available_height)
        switch_radius = switch_size // 2

        # Center the switch in the available space
        switch_center_x = rect.center().x()
        switch_center_y = rect.top() + switch_radius + 5  # 5px top margin
        switch_center = QPoint(switch_center_x, switch_center_y)

        ring_thickness = 8

        # If widget is disabled, draw with very muted colors
        is_disabled = not self.isEnabled()

        # Draw brightness-based semicircular ring
        ring_rect = QRect(switch_center.x() - switch_radius, switch_center.y() - switch_radius,
                         switch_size, switch_size)

        if self.is_on and self.brightness > 0 and not is_disabled:
            # Calculate arc span based on brightness (0-100% -> 0-360°)
            # Start from top (90°) and go clockwise
            start_angle = 90 * 16  # 90° in Qt's 1/16th degree units (top position)
            arc_span = int((self.brightness / 100.0) * 360 * 16)  # Convert to 1/16th degrees

            # Use FULL BRIGHTNESS version of the color (vibrant and true)
            vibrant_color = QColor.fromHsv(self.hue, int(self.saturation * 2.55), 255)  # Always max brightness (255)
            ring_pen = QPen(vibrant_color, ring_thickness, Qt.SolidLine, Qt.RoundCap)
            painter.setPen(ring_pen)
            painter.setBrush(Qt.NoBrush)

            # Draw the arc representing brightness level
            painter.drawArc(ring_rect, start_angle, arc_span)

            # Optionally draw a subtle background ring to show the full potential
            background_pen = QPen(QColor(60, 60, 60), ring_thickness // 2)
            painter.setPen(background_pen)
            painter.drawEllipse(ring_rect)
        else:
            # When off or disabled, draw a very subtle background ring
            bg_color = QColor(40, 40, 40) if is_disabled else QColor(50, 50, 50)
            background_pen = QPen(bg_color, ring_thickness // 2)
            painter.setPen(background_pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(ring_rect)

        # Draw inner circle (button background)
        inner_radius = switch_radius - ring_thickness - 5
        # Darker gray when disabled
        inner_color = QColor(60, 60, 60) if is_disabled else QColor(80, 80, 80)
        inner_brush = QBrush(inner_color)

        border_color = QColor(80, 80, 80) if is_disabled else QColor(120, 120, 120)
        painter.setPen(QPen(border_color, 2))
        painter.setBrush(inner_brush)
        inner_rect = QRect(switch_center.x() - inner_radius, switch_center.y() - inner_radius,
                          inner_radius * 2, inner_radius * 2)
        painter.drawEllipse(inner_rect)

        # Draw power button icon (centered in inner circle)
        if is_disabled:
            # Very dark gray when disabled
            icon_color = QColor(80, 80, 80)
        elif self.is_on:
            # Use FULL BRIGHTNESS version of the color (same as ring)
            icon_color = QColor.fromHsv(self.hue, int(self.saturation * 2.55), 255)  # Always max brightness (255)
        else:
            # Dark gray when off
            icon_color = QColor(140, 140, 140)

        painter.setPen(QPen(icon_color, 3))
        painter.setBrush(Qt.NoBrush)

        # Power symbol (circle with gap and line) - centered
        icon_radius = inner_radius // 2
        icon_center = switch_center  # Use the same center as the switch

        # Arc (circle with gap at top)
        arc_rect = QRect(icon_center.x() - icon_radius, icon_center.y() - icon_radius,
                        icon_radius * 2, icon_radius * 2)
        painter.drawArc(arc_rect, 135 * 16, 270 * 16)  # 135° to 45° (270° arc with gap at top)

        # Vertical line at top
        painter.drawLine(icon_center.x(), icon_center.y() - icon_radius,
                        icon_center.x(), icon_center.y() - icon_radius // 3)

        # Draw sync status indicator (small dot in corner)
        if not self.is_synced and not is_disabled:
            # Red dot for out-of-sync (only show when enabled)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(255, 100, 100)))
            sync_x = rect.right() - 10
            sync_y = rect.top() + 10
            painter.drawEllipse(sync_x - 3, sync_y - 3, 6, 6)

        # Draw label (centered at bottom) - dimmed when disabled
        label_color = QColor(100, 100, 100) if is_disabled else QColor(220, 220, 220)
        painter.setPen(QPen(label_color))
        painter.setFont(QFont("Arial", 10))
        label_rect = QRect(rect.left(), rect.bottom() - 25, rect.width(), 20)
        painter.drawText(label_rect, Qt.AlignCenter, self.label)


class ColorWheelDialog(QDialog):
    """
    Color wheel dialog for advanced color selection.
    Mimics the Poco app's color wheel interface.
    """
    color_changed = pyqtSignal(int, int, int)  # hue, saturation, brightness

    def __init__(self, parent=None, switch=None, initial_hue=0, initial_sat=100, initial_bright=100):
        super().__init__(parent)
        self.switch = switch
        self.parent_gui = parent  # Reference to main GUI for CAN access
        self.current_pocofx_id = 0  # Track current PocoFx
        self.is_pocofx_playing = False

        # Setup logging
        import logging
        self.logger = logging.getLogger(f"{__name__}.ColorWheelDialog")

        # Create rate limiter for color commands within dialog (100ms = 10Hz max rate)
        self.dialog_color_rate_limiter = CommandRateLimiter(delay_ms=100)

        self.setWindowTitle("Color Control")
        self.setModal(True)
        self.setFixedSize(450, 1050)  # Increased height to fully show color wheel and all controls

        # Apply dark theme
        self.setStyleSheet("""
            QDialog {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QPushButton {
                background-color: #404040;
                border: 1px solid #606060;
                border-radius: 8px;
                padding: 8px 16px;
                color: #ffffff;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #505050;
            }
            QPushButton:pressed {
                background-color: #353535;
            }
            QLabel {
                color: #ffffff;
                font-size: 14px;
            }
        """)

        self.hue = initial_hue
        self.saturation = initial_sat
        self.brightness = initial_bright

        self._setup_ui()

        # Connect to parent's device state update signal to sync with device changes
        if parent and hasattr(parent, 'device_state_signal'):
            parent.device_state_signal.connect(self._on_device_state_update)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)  # Optimized spacing for better fit
        layout.setContentsMargins(15, 10, 15, 10)  # Reduced top/bottom margins

        # Title
        title = QLabel("Color & Brightness")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Arial", 18, QFont.Bold))
        layout.addWidget(title)

        # RGB Preset buttons at the top
        rgb_frame = QFrame()
        rgb_layout = QVBoxLayout(rgb_frame)
        rgb_layout.setSpacing(5)

        rgb_title = QLabel("Quick Colors")
        rgb_title.setAlignment(Qt.AlignCenter)
        rgb_layout.addWidget(rgb_title)

        rgb_buttons_layout = QHBoxLayout()

        # Create RGB preset buttons
        red_btn = QPushButton("Red")
        red_btn.setStyleSheet("QPushButton { background-color: #cc0000; } QPushButton:hover { background-color: #ff0000; }")
        red_btn.clicked.connect(lambda: self._set_preset_color(0, 255, 0))  # Red hue/sat, brightness ignored
        rgb_buttons_layout.addWidget(red_btn)

        green_btn = QPushButton("Green")
        green_btn.setStyleSheet("QPushButton { background-color: #00aa00; } QPushButton:hover { background-color: #00ff00; }")
        green_btn.clicked.connect(lambda: self._set_preset_color(85, 255, 0))  # Green hue/sat, brightness ignored
        rgb_buttons_layout.addWidget(green_btn)

        blue_btn = QPushButton("Blue")
        blue_btn.setStyleSheet("QPushButton { background-color: #0000cc; } QPushButton:hover { background-color: #0000ff; }")
        blue_btn.clicked.connect(lambda: self._set_preset_color(170, 255, 0))  # Blue hue/sat, brightness ignored
        rgb_buttons_layout.addWidget(blue_btn)

        rgb_layout.addLayout(rgb_buttons_layout)
        layout.addWidget(rgb_frame)

        # Color wheel (centered with proper padding)
        wheel_frame = QFrame()
        wheel_frame.setFrameStyle(QFrame.StyledPanel)
        wheel_frame.setStyleSheet("QFrame { background-color: #1a1a1a; border: 1px solid #404040; border-radius: 8px; padding: 10px; }")
        wheel_layout = QHBoxLayout(wheel_frame)
        wheel_layout.setContentsMargins(15, 15, 15, 15)  # Add padding around the wheel

        self.color_wheel = ColorWheel(self.hue, self.saturation, self.brightness)
        self.color_wheel.color_changed.connect(self._on_color_changed)

        wheel_layout.addWidget(self.color_wheel, 0, Qt.AlignCenter)

        layout.addWidget(wheel_frame)

        # Brightness controls
        brightness_frame = QFrame()
        brightness_layout = QVBoxLayout(brightness_frame)
        brightness_layout.setSpacing(5)

        brightness_label = QLabel("Brightness")
        brightness_label.setAlignment(Qt.AlignCenter)
        brightness_layout.addWidget(brightness_label)

        # Brightness control row with dimming buttons
        brightness_control_layout = QHBoxLayout()

        # Dim down button
        self.dim_down_btn = QPushButton("−")
        self.dim_down_btn.setFixedSize(45, 45)
        self.dim_down_btn.setToolTip("Dim down 10% (uses device native dimming)")
        self.dim_down_btn.clicked.connect(self._dim_down)
        self.dim_down_btn.setStyleSheet("""
            QPushButton {
                font-size: 18px;
                font-weight: bold;
                color: #ffffff;
                background-color: #505050;
                border: 1px solid #707070;
                border-radius: 22px;
            }
            QPushButton:hover {
                background-color: #606060;
            }
            QPushButton:pressed {
                background-color: #404040;
            }
        """)
        brightness_control_layout.addWidget(self.dim_down_btn)

        # Horizontal brightness slider
        self.brightness_slider = QSlider(Qt.Horizontal)
        self.brightness_slider.setMinimum(10)  # Minimum 10% brightness
        self.brightness_slider.setMaximum(100)  # Maximum 100% brightness
        self.brightness_slider.setValue(self.brightness)
        self.brightness_slider.setFixedHeight(30)
        self.brightness_slider.valueChanged.connect(self._on_brightness_changed)
        self.brightness_slider.setToolTip("Precise brightness control (direct to device)")

        # Style the slider
        self.brightness_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #999999;
                height: 8px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #B1B1B1, stop:1 #c4c4c4);
                margin: 2px 0;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #b4b4b4, stop:1 #8f8f8f);
                border: 1px solid #5c5c5c;
                width: 18px;
                margin: -2px 0;
                border-radius: 9px;
            }
            QSlider::handle:horizontal:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ffffff, stop:1 #a8a8a8);
            }
        """)

        brightness_control_layout.addWidget(self.brightness_slider)

        # Dim up button
        self.dim_up_btn = QPushButton("+")
        self.dim_up_btn.setFixedSize(45, 45)
        self.dim_up_btn.setToolTip("Dim up 10% (uses device native dimming)")
        self.dim_up_btn.clicked.connect(self._dim_up)
        self.dim_up_btn.setStyleSheet("""
            QPushButton {
                font-size: 18px;
                font-weight: bold;
                color: #ffffff;
                background-color: #505050;
                border: 1px solid #707070;
                border-radius: 22px;
            }
            QPushButton:hover {
                background-color: #606060;
            }
            QPushButton:pressed {
                background-color: #404040;
            }
        """)
        brightness_control_layout.addWidget(self.dim_up_btn)

        # Delta brightness controls
        delta_layout = QHBoxLayout()

        delta_label = QLabel("Δ")
        delta_label.setStyleSheet("color: #ffffff; font-size: 16px; font-weight: bold;")
        delta_layout.addWidget(delta_label)

        self.delta_spinbox = QSpinBox()
        self.delta_spinbox.setRange(-128, 127)
        self.delta_spinbox.setValue(32)  # Default to +32 (about 12.7%)
        self.delta_spinbox.setFixedWidth(70)
        self.delta_spinbox.setToolTip("Brightness delta (-128 to +127)")
        self.delta_spinbox.setStyleSheet("""
            QSpinBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #505050;
                border-radius: 4px;
                padding: 2px;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #404040;
                border: 1px solid #606060;
                width: 16px;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background-color: #505050;
            }
        """)
        delta_layout.addWidget(self.delta_spinbox)

        delta_apply_btn = QPushButton("Apply")
        delta_apply_btn.setFixedSize(50, 30)
        delta_apply_btn.setToolTip("Apply brightness delta")
        delta_apply_btn.clicked.connect(self._delta_brightness)
        delta_apply_btn.setStyleSheet("""
            QPushButton {
                font-size: 10px;
                color: #ffffff;
                background-color: #505050;
                border: 1px solid #707070;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #606060;
            }
            QPushButton:pressed {
                background-color: #404040;
            }
        """)
        delta_layout.addWidget(delta_apply_btn)

        brightness_control_layout.addLayout(delta_layout)

        brightness_layout.addLayout(brightness_control_layout)
        layout.addWidget(brightness_frame)

        # RGB Value controls
        rgb_values_frame = QFrame()
        rgb_values_frame.setFrameStyle(QFrame.StyledPanel)
        rgb_values_frame.setStyleSheet("QFrame { background-color: #1a1a1a; border: 1px solid #404040; border-radius: 8px; padding: 10px; }")
        rgb_values_layout = QVBoxLayout(rgb_values_frame)
        rgb_values_layout.setSpacing(8)

        rgb_values_title = QLabel("RGB Values")
        rgb_values_title.setAlignment(Qt.AlignCenter)
        rgb_values_title.setFont(QFont("Arial", 12, QFont.Bold))
        rgb_values_layout.addWidget(rgb_values_title)

        # RGB sliders
        rgb_sliders_layout = QVBoxLayout()
        rgb_sliders_layout.setSpacing(10)

        # Red slider
        red_row = QHBoxLayout()
        red_label = QLabel("Red")
        red_label.setFixedWidth(50)
        red_row.addWidget(red_label)

        self.red_slider = QSlider(Qt.Horizontal)
        self.red_slider.setRange(0, 255)
        self.red_slider.setValue(255)
        self.red_slider.setFixedHeight(25)
        self.red_slider.valueChanged.connect(self._on_rgb_changed)
        self.red_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #999999;
                height: 8px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #000000, stop:1 #ff0000);
                margin: 2px 0;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #ffffff, stop:1 #cccccc);
                border: 1px solid #5c5c5c;
                width: 18px;
                margin: -2px 0;
                border-radius: 9px;
            }
            QSlider::handle:horizontal:hover {
                background: #ffffff;
            }
        """)
        red_row.addWidget(self.red_slider)

        self.red_value_label = QLabel("255")
        self.red_value_label.setFixedWidth(35)
        self.red_value_label.setAlignment(Qt.AlignRight)
        red_row.addWidget(self.red_value_label)
        rgb_sliders_layout.addLayout(red_row)

        # Green slider
        green_row = QHBoxLayout()
        green_label = QLabel("Green")
        green_label.setFixedWidth(50)
        green_row.addWidget(green_label)

        self.green_slider = QSlider(Qt.Horizontal)
        self.green_slider.setRange(0, 255)
        self.green_slider.setValue(255)
        self.green_slider.setFixedHeight(25)
        self.green_slider.valueChanged.connect(self._on_rgb_changed)
        self.green_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #999999;
                height: 8px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #000000, stop:1 #00ff00);
                margin: 2px 0;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #ffffff, stop:1 #cccccc);
                border: 1px solid #5c5c5c;
                width: 18px;
                margin: -2px 0;
                border-radius: 9px;
            }
            QSlider::handle:horizontal:hover {
                background: #ffffff;
            }
        """)
        green_row.addWidget(self.green_slider)

        self.green_value_label = QLabel("255")
        self.green_value_label.setFixedWidth(35)
        self.green_value_label.setAlignment(Qt.AlignRight)
        green_row.addWidget(self.green_value_label)
        rgb_sliders_layout.addLayout(green_row)

        # Blue slider
        blue_row = QHBoxLayout()
        blue_label = QLabel("Blue")
        blue_label.setFixedWidth(50)
        blue_row.addWidget(blue_label)

        self.blue_slider = QSlider(Qt.Horizontal)
        self.blue_slider.setRange(0, 255)
        self.blue_slider.setValue(255)
        self.blue_slider.setFixedHeight(25)
        self.blue_slider.valueChanged.connect(self._on_rgb_changed)
        self.blue_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #999999;
                height: 8px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #000000, stop:1 #0000ff);
                margin: 2px 0;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #ffffff, stop:1 #cccccc);
                border: 1px solid #5c5c5c;
                width: 18px;
                margin: -2px 0;
                border-radius: 9px;
            }
            QSlider::handle:horizontal:hover {
                background: #ffffff;
            }
        """)
        blue_row.addWidget(self.blue_slider)

        self.blue_value_label = QLabel("255")
        self.blue_value_label.setFixedWidth(35)
        self.blue_value_label.setAlignment(Qt.AlignRight)
        blue_row.addWidget(self.blue_value_label)
        rgb_sliders_layout.addLayout(blue_row)

        rgb_values_layout.addLayout(rgb_sliders_layout)

        # Send RGB button
        send_rgb_btn = QPushButton("Send RGB")
        send_rgb_btn.setFixedHeight(35)
        send_rgb_btn.setToolTip("Send RGB values directly")
        send_rgb_btn.clicked.connect(self._send_rgb_command)
        send_rgb_btn.setStyleSheet("""
            QPushButton {
                background-color: #005500;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #007700;
            }
            QPushButton:pressed {
                background-color: #003300;
            }
        """)
        rgb_values_layout.addWidget(send_rgb_btn)

        layout.addWidget(rgb_values_frame)

        # Initialize RGB values from initial HSB
        self._update_rgb_from_hsb(block_signals=True)

        # Flag to prevent circular updates
        self._updating_from_wheel = False

        # PocoFx controls
        pocofx_frame = QFrame()
        pocofx_layout = QVBoxLayout(pocofx_frame)
        pocofx_layout.setSpacing(5)

        # pocofx selection row
        pocofx_select_layout = QHBoxLayout()

        pocofx_label = QLabel("PocoFx")
        pocofx_label.setAlignment(Qt.AlignCenter)
        pocofx_select_layout.addWidget(pocofx_label)

        # PocoFx selection dropdown
        self.pocofx_combo = QComboBox()
        for fx in POCOFX_DATA:
            self.pocofx_combo.addItem(fx['name'])

        # create a lookup to map index and PocoFx ID
        self.pocofx_combo.currentIndexChanged.connect(self._on_pocofx_selected)
        pocofx_select_layout.addWidget(self.pocofx_combo)

        pocofx_layout.addLayout(pocofx_select_layout)

        # PocoFx control buttons row
        pocofx_buttons_layout = QHBoxLayout()

        self.play_pause_btn = QPushButton("▶")
        self.play_pause_btn.setFixedSize(40, 30)
        self.play_pause_btn.clicked.connect(self._toggle_pocofx_playback)
        pocofx_buttons_layout.addWidget(self.play_pause_btn)

        self.stop_btn = QPushButton("⏹")
        self.stop_btn.setFixedSize(40, 30)
        self.stop_btn.clicked.connect(self._stop_pocofx)
        pocofx_buttons_layout.addWidget(self.stop_btn)

        pocofx_buttons_layout.addStretch()
        pocofx_layout.addLayout(pocofx_buttons_layout)

        layout.addWidget(pocofx_frame)

        # Done button
        done_btn = QPushButton("Done")
        done_btn.clicked.connect(self.accept)
        layout.addWidget(done_btn)

    def _on_color_changed(self, hue, saturation, brightness):
        # Update internal state immediately for responsive GUI
        self.hue = hue
        self.saturation = saturation
        self.brightness = brightness

        # Update RGB spinboxes to match new HSB values (without triggering callbacks)
        if not self._updating_from_wheel:
            self._updating_from_wheel = True
            self._update_rgb_from_hsb(block_signals=True)
            self._updating_from_wheel = False

        # Rate-limit the actual CAN command sending
        if self.parent_gui and self.parent_gui.poco:
            self.dialog_color_rate_limiter.queue_command(
                lambda: self._send_color_command(hue, saturation, brightness)
            )

    def _on_brightness_changed(self, value):
        """Handle brightness slider changes"""
        # Update internal state and GUI immediately for responsiveness
        self.brightness = value
        self.color_wheel.set_brightness(self.brightness)

        # Rate-limit the actual CAN command sending
        if self.parent_gui and self.parent_gui.poco:
            self.dialog_color_rate_limiter.queue_command(
                lambda: self._send_color_command(self.hue, self.saturation, self.brightness)
            )

    def _send_color_command(self, hue, saturation, brightness):
        """Send color command to CAN bus (called by rate limiter)"""
        if not self.switch or not self.parent_gui or not self.parent_gui.poco:
            return

        try:
            # Convert to Poco protocol values (0-255) with proper rounding and clamping
            poco_hue = max(0, min(255, round((hue / 360) * 255)))
            poco_sat = max(0, min(255, round((saturation / 100) * 255)))
            poco_bright = max(0, min(255, round((brightness / 100) * 255)))

            # Send the actual CAN command
            self.logger.debug(f"Sending CAN command - H:{poco_hue} S:{poco_sat} B:{poco_bright}")
            self.parent_gui.poco.set_color(self.switch.switch_id, poco_hue, poco_sat, poco_bright)
            self.logger.debug(f"CAN command sent successfully")

            # Update main switch widget only when command is actually sent (rate-limited)
            self.switch.set_state(True, synced=False)  # Turn on the switch visually
            self.switch.set_color(hue, saturation, brightness, synced=False)

            self.parent_gui.status_label.setText(f"Color set for Switch {self.switch.switch_id+1}")
        except Exception as e:
            self.parent_gui.status_label.setText(f"CAN error: {str(e)}")
            self.logger.error(f"Color command error: {e}")

    def _dim_up(self):
        """Handle dim up button - uses native firmware dim command"""
        if not self.switch or not self.parent_gui or not self.parent_gui.poco:
            return

        try:
            self.logger.debug(f"Using native dim_up() command for switch {self.switch.switch_id}")

            # Use the native CAN dim_up command (should preserve color with firmware fix)
            self.parent_gui.poco.dim_up(self.switch.switch_id)

            # Optimistically update GUI brightness (+10%)
            new_brightness = min(100, self.brightness + 10)
            self.brightness = new_brightness

            # Block signals to prevent triggering color_changed emission
            self.brightness_slider.blockSignals(True)
            self.brightness_slider.setValue(new_brightness)
            self.brightness_slider.blockSignals(False)

            self.color_wheel.set_brightness(new_brightness)

            # Don't emit color_changed - let firmware handle color preservation with dim command

        except Exception as e:
            self.logger.error(f"Dim up error: {e}")

    def _dim_down(self):
        """Handle dim down button - uses native firmware dim command"""
        if not self.switch or not self.parent_gui or not self.parent_gui.poco:
            return

        try:
            self.logger.debug(f"Using native dim_down() command for switch {self.switch.switch_id}")

            # Use the native CAN dim_down command (should preserve color with firmware fix)
            self.parent_gui.poco.dim_down(self.switch.switch_id)

            # Optimistically update GUI brightness (-10%, minimum 10%)
            new_brightness = max(10, self.brightness - 10)

            self.brightness = new_brightness

            # Block signals to prevent triggering color_changed emission
            self.brightness_slider.blockSignals(True)
            self.brightness_slider.setValue(new_brightness)
            self.brightness_slider.blockSignals(False)

            self.color_wheel.set_brightness(new_brightness)

            # Don't emit color_changed - let firmware handle color preservation with dim command

        except Exception as e:
            self.logger.error(f"Dim down error: {e}")

    def _delta_brightness(self):
        """Handle delta brightness button - uses native firmware delta brightness command"""
        if not self.switch or not self.parent_gui or not self.parent_gui.poco:
            return

        try:
            # Get delta value from spinbox
            delta = self.delta_spinbox.value()
            self.logger.debug(f"Using native delta_brightness() command for switch {self.switch.switch_id} with delta {delta}")

            # Use the native CAN delta_brightness command with specified delta
            self.parent_gui.poco.delta_brightness(self.switch.switch_id, delta)

            # Optimistically update GUI brightness (convert delta to percentage and clamp to 10-100%)
            delta_percent = (delta / 255) * 100  # Convert from -128/+127 range to percentage
            new_brightness = max(10, min(100, self.brightness + delta_percent))
            self.brightness = int(new_brightness)  # Convert to int for GUI controls

            # Block signals to prevent triggering color_changed emission
            self.brightness_slider.blockSignals(True)
            self.brightness_slider.setValue(self.brightness)
            self.brightness_slider.blockSignals(False)

            self.color_wheel.set_brightness(self.brightness)

            # Don't emit color_changed - let firmware handle color preservation

        except Exception as e:
            self.logger.error(f"Delta brightness error: {e}")

    def _set_preset_color(self, poco_hue, poco_sat, poco_bright_ignored):
        """Set a preset color using device protocol values and set brightness to full"""
        # Convert Poco protocol values (0-255) back to HSV (0-360, 0-100, 0-100) for the color wheel display
        hue = (poco_hue / 255) * 360
        saturation = (poco_sat / 255) * 100
        # Set brightness to full (100%)
        brightness = 100

        # Update internal state
        self.hue = hue
        self.saturation = saturation
        self.brightness = brightness

        # Update the color wheel display
        self.color_wheel.hue = hue
        self.color_wheel.saturation = saturation
        self.color_wheel.brightness = brightness
        self.color_wheel.update()

        # Update brightness slider to show full brightness
        self.brightness_slider.blockSignals(True)
        self.brightness_slider.setValue(100)
        self.brightness_slider.blockSignals(False)

        # Call the color change handler directly to send the command
        self._on_color_changed(hue, saturation, brightness)

    def _on_pocofx_selected(self, pocofx_index):
        """Handle PocoFx selection from dropdown"""
        if not self.switch or not self.parent_gui or not self.parent_gui.poco:
            return

        # Update current PocoFx ID (0 = no PocoFx, 1-9 = PocoFxs)
        self.current_pocofx_id = pocofx_index

        if pocofx_index == 0:
            # "None" selected - stop any running PocoFx
            self._stop_pocofx()
        else:
            # Start the selected PocoFx
            try:
                self.parent_gui.poco.start_pocofx(self.switch.switch_id, POCOFX_DATA[pocofx_index]['FxId'])
                self.is_pocofx_playing = True
                self.play_pause_btn.setText("⏸")
                self.parent_gui.status_label.setText(f"Started PocoFx '{POCOFX_DATA[pocofx_index]['name']}' ({POCOFX_DATA[pocofx_index]['FxId']}) on Switch {self.switch.switch_id+1}")
            except Exception as e:
                self.parent_gui.status_label.setText(f"PocoFx error: {str(e)}")

    def _toggle_pocofx_playback(self):
        """Toggle PocoFx play/pause"""
        if not self.switch or not self.parent_gui or not self.parent_gui.poco:
            return

        try:
            if self.current_pocofx_id > 0:  # Only if a PocoFx is selected
                self.parent_gui.poco.pause_pocofx(self.switch.switch_id)
                self.is_pocofx_playing = not self.is_pocofx_playing
                self.play_pause_btn.setText("⏸" if self.is_pocofx_playing else "▶")
                status = "resumed" if self.is_pocofx_playing else "paused"
                self.parent_gui.status_label.setText(f"PocoFx {status} on Switch {self.switch.switch_id+1}")
        except Exception as e:
            self.parent_gui.status_label.setText(f"PocoFx error: {str(e)}")

    def _stop_pocofx(self):
        """Stop current PocoFx and return to solid color"""
        if not self.switch or not self.parent_gui or not self.parent_gui.poco:
            return

        try:
            # Turn off PocoFx by setting solid color
            poco_hue = round((self.hue / 360) * 255)
            poco_sat = round((self.saturation / 100) * 255)
            poco_bright = round((self.brightness / 100) * 255)

            self.parent_gui.poco.set_color(self.switch.switch_id, poco_hue, poco_sat, poco_bright)

            # Reset PocoFx state
            self.current_pocofx_id = 0
            self.is_pocofx_playing = False
            self.pocofx_combo.setCurrentIndex(0)
            self.play_pause_btn.setText("▶")
            self.parent_gui.status_label.setText(f"PocoFx stopped on Switch {self.switch.switch_id+1}")
        except Exception as e:
            self.parent_gui.status_label.setText(f"PocoFx error: {str(e)}")

    def _update_rgb_from_hsb(self, block_signals=False):
        """Update RGB sliders from current HSB values"""
        # Convert HSB to RGB
        # colorsys uses H=0-1, S=0-1, V=0-1
        h_norm = self.hue / 360.0
        s_norm = self.saturation / 100.0
        v_norm = self.brightness / 100.0

        r, g, b = colorsys.hsv_to_rgb(h_norm, s_norm, v_norm)

        # Convert to 0-255 range
        red = int(round(r * 255))
        green = int(round(g * 255))
        blue = int(round(b * 255))

        # Update sliders
        if block_signals:
            self.red_slider.blockSignals(True)
            self.green_slider.blockSignals(True)
            self.blue_slider.blockSignals(True)

        self.red_slider.setValue(red)
        self.green_slider.setValue(green)
        self.blue_slider.setValue(blue)

        # Update value labels
        self.red_value_label.setText(str(red))
        self.green_value_label.setText(str(green))
        self.blue_value_label.setText(str(blue))

        if block_signals:
            self.red_slider.blockSignals(False)
            self.green_slider.blockSignals(False)
            self.blue_slider.blockSignals(False)

    def _on_rgb_changed(self, value):
        """Handle RGB slider changes - update HSB values"""
        # Prevent circular updates
        if self._updating_from_wheel:
            return

        # Get current RGB values
        red = self.red_slider.value()
        green = self.green_slider.value()
        blue = self.blue_slider.value()

        # Update value labels
        self.red_value_label.setText(str(red))
        self.green_value_label.setText(str(green))
        self.blue_value_label.setText(str(blue))

        # Convert to normalized 0-1 range
        r_norm = red / 255.0
        g_norm = green / 255.0
        b_norm = blue / 255.0

        # Convert RGB to HSV
        h_norm, s_norm, v_norm = colorsys.rgb_to_hsv(r_norm, g_norm, b_norm)

        # Convert to our ranges (H=0-360, S=0-100, V=0-100)
        hue = h_norm * 360
        saturation = s_norm * 100
        brightness = v_norm * 100

        # Update internal state
        self.hue = hue
        self.saturation = saturation
        self.brightness = brightness

        # Update color wheel (block signals to prevent recursion)
        self._updating_from_wheel = True
        self.color_wheel.hue = hue
        self.color_wheel.saturation = saturation
        self.color_wheel.brightness = brightness
        self.color_wheel.update()

        # Update brightness slider
        self.brightness_slider.blockSignals(True)
        self.brightness_slider.setValue(int(brightness))
        self.brightness_slider.blockSignals(False)

        self._updating_from_wheel = False

    def _send_rgb_command(self):
        """Send RGB values directly using RGB command"""
        if not self.switch or not self.parent_gui or not self.parent_gui.poco:
            return

        try:
            red = self.red_slider.value()
            green = self.green_slider.value()
            blue = self.blue_slider.value()

            self.logger.info(f"Sending RGB command - R:{red} G:{green} B:{blue}")
            self.parent_gui.poco.send_vsw_rgb(self.switch.switch_id, red, green, blue)

            # Update main switch widget
            self.switch.set_state(True, synced=False)
            self.switch.set_color(self.hue, self.saturation, self.brightness, synced=False)

            self.parent_gui.status_label.setText(f"RGB sent to Switch {self.switch.switch_id+1}: R={red} G={green} B={blue}")
        except Exception as e:
            self.parent_gui.status_label.setText(f"RGB command error: {str(e)}")
            self.logger.error(f"RGB command error: {e}")

    def _on_device_state_update(self, switch_id: int, device_state):
        """
        Handle device state updates for the switch this dialog controls.
        Updates the dialog controls to reflect the current device state.
        """
        # Only update if this is for our switch
        if self.switch and switch_id == self.switch.switch_id:
            # Convert device HSB (0-255) to GUI HSB (0-360, 0-100, 0-100)
            gui_hue = int((device_state.hue / 255) * 360)
            gui_sat = int((device_state.saturation / 255) * 100)
            gui_bright = int((device_state.brightness / 255) * 100)

            # Update internal state (keep color even when off)
            self.hue = gui_hue
            self.saturation = gui_sat
            self.brightness = gui_bright

            # Update GUI controls (block signals to avoid feedback loops)
            self.color_wheel.blockSignals(True)
            self.color_wheel.set_color(gui_hue, gui_sat, gui_bright)
            self.color_wheel.blockSignals(False)

            self.brightness_slider.blockSignals(True)
            self.brightness_slider.setValue(gui_bright)
            self.brightness_slider.blockSignals(False)

            self.logger.debug(f"ColorWheelDialog updated for switch {switch_id}: "
                            f"H={gui_hue} S={gui_sat} B={gui_bright}")

    def closeEvent(self, event):
        """Clean up signal connections when dialog closes."""
        # Disconnect from parent's device state signal
        if self.parent_gui and hasattr(self.parent_gui, 'device_state_signal'):
            try:
                self.parent_gui.device_state_signal.disconnect(self._on_device_state_update)
            except:
                pass  # Signal might already be disconnected
        super().closeEvent(event)


class ColorWheel(QWidget):
    """
    Interactive color wheel widget for hue and saturation selection.
    """
    color_changed = pyqtSignal(int, int, int)  # hue, saturation, brightness

    def __init__(self, hue=0, saturation=100, brightness=100):
        super().__init__()
        self.hue = hue
        self.saturation = saturation
        self.brightness = brightness
        self.setMinimumSize(320, 320)
        self.setFixedSize(320, 320)  # Color wheel sized for new layout
        self._wheel_pixmap = None
        self._cached_brightness = -1
        self._cached_size = None

    def set_brightness(self, brightness):
        self.brightness = brightness
        self.update()

    def set_color(self, hue, saturation, brightness):
        """Update the color wheel to show the specified color"""
        self.hue = hue
        self.saturation = saturation
        self.brightness = brightness
        self.update()

    def mousePressEvent(self, event):
        self._update_color_from_position(event.pos())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:  # Only update while dragging
            self._update_color_from_position(event.pos())

    def _update_color_from_position(self, pos):
        center = QPoint(self.width() // 2, self.height() // 2)
        dx = pos.x() - center.x()
        dy = pos.y() - center.y()

        distance = math.sqrt(dx * dx + dy * dy)
        max_radius = min(self.width(), self.height()) // 2 - 10

        # Calculate hue from angle (works for both inside and outside the wheel)
        angle = math.atan2(dy, dx)
        new_hue = int((math.degrees(angle) + 90 + 360) % 360)  # +90 rotates red to top

        # Calculate saturation based on distance
        if distance <= max_radius:
            # Inside the wheel: saturation based on distance from center
            new_saturation = int((distance / max_radius) * 100)
        else:
            # Outside the wheel: full saturation (100%)
            new_saturation = 100

        # Only update if values actually changed
        if new_hue != self.hue or new_saturation != self.saturation:
            self.hue = new_hue
            self.saturation = new_saturation
            self.update()
            self.color_changed.emit(self.hue, self.saturation, self.brightness)

    def _create_wheel_pixmap(self):
        """Create cached pixmap of the color wheel using pixel-based drawing"""
        size = self.size()
        image = QImage(size, QImage.Format_ARGB32)
        image.fill(Qt.transparent)

        center_x = size.width() // 2
        center_y = size.height() // 2
        max_radius = min(size.width(), size.height()) // 2 - 10

        # Draw color wheel pixel by pixel for smooth gradients
        for y in range(size.height()):
            for x in range(size.width()):
                # Calculate distance from center
                dx = x - center_x
                dy = y - center_y
                distance = math.sqrt(dx * dx + dy * dy)

                if distance <= max_radius:
                    # Calculate hue from angle (rotate so red is at top)
                    angle = math.atan2(dy, dx)
                    hue = int((math.degrees(angle) + 90 + 360) % 360)  # +90 rotates red to top

                    # Calculate saturation from distance (0 at center, 255 at edge)
                    saturation = int((distance / max_radius) * 255)

                    # Use current brightness
                    brightness_val = int(self.brightness * 2.55)

                    # Create color and set pixel
                    color = QColor.fromHsv(hue, saturation, brightness_val)
                    image.setPixelColor(x, y, color)

        # Convert QImage to QPixmap
        return QPixmap.fromImage(image)

    def paintEvent(self, event):
        # Check if we need to regenerate the wheel pixmap
        current_size = self.size()
        if (self._wheel_pixmap is None or
            self._cached_brightness != self.brightness or
            self._cached_size != current_size):

            self._wheel_pixmap = self._create_wheel_pixmap()
            self._cached_brightness = self.brightness
            self._cached_size = current_size

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Draw the cached color wheel
        painter.drawPixmap(0, 0, self._wheel_pixmap)

        # Draw selection indicator
        rect = self.rect()
        center = rect.center()
        radius = min(rect.width(), rect.height()) // 2 - 10

        sel_radius = (self.saturation / 100) * radius
        sel_x = center.x() + sel_radius * math.cos(math.radians(self.hue - 90))  # -90 to match rotation
        sel_y = center.y() + sel_radius * math.sin(math.radians(self.hue - 90))  # -90 to match rotation

        # White circle with black border for good visibility
        painter.setPen(QPen(Qt.black, 2))
        painter.setBrush(QBrush(Qt.white))
        painter.drawEllipse(int(sel_x - 6), int(sel_y - 6), 12, 12)


class VirtualSwitchesGUI(QMainWindow):
    """GUI for controlling Poco via ExtSw CAN Protocol."""

    # Signal for thread-safe GUI updates
    device_state_signal = pyqtSignal(int, object)  # switch_id, device_state

    def __init__(self):
        super().__init__()
        self.poco = None
        self.switches = []

        self.setWindowTitle("Poco Level 2: Virtual Switch Actions")
        self.setGeometry(100, 100, 500, 600)

        # Enhanced stylesheet with better disabled state visibility
        enhanced_stylesheet = DARK_THEME_STYLESHEET + """
            QPushButton:disabled {
                background-color: #2a2a2a;
                color: #555555;
                border: 1px solid #3a3a3a;
            }
        """
        self.setStyleSheet(enhanced_stylesheet)

        # Connect signal for thread-safe GUI updates
        self.device_state_signal.connect(self._on_device_state_update_safe)

        self._setup_ui()

    def _setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)
        layout.setSpacing(20)
        layout.setContentsMargins(20, 20, 20, 20)

        # Title
        title = create_title_label("Poco Level 2: Virtual Switches (Actions)")
        layout.addWidget(title)

        # CAN connection widget
        self.can_widget = CANConnectionWidget("Lumitec", "PocoLevel2VSw")
        self.can_widget.connected.connect(self._on_can_connected)
        self.can_widget.disconnected.connect(self._on_can_disconnected)
        self.can_widget.connection_failed.connect(self._on_can_connection_failed)
        layout.addWidget(self.can_widget)

        # Switch grid (2x2)
        switches_frame = QFrame()
        switches_layout = QGridLayout(switches_frame)
        switches_layout.setSpacing(20)

        switch_labels = ["Switch 1", "Switch 2", "Switch 3", "Switch 4"]

        for i in range(4):
            row = i // 2
            col = i % 2

            switch = CircularSwitch(i, switch_labels[i])
            switch.clicked.connect(lambda s=switch: self._switch_clicked(s))
            switch.long_pressed.connect(lambda s=switch: self._switch_long_pressed(s))

            self.switches.append(switch)
            switches_layout.addWidget(switch, row, col)

        layout.addWidget(switches_frame)

        # Disable all switches initially (until CAN connection established)
        for switch in self.switches:
            switch.setEnabled(False)

        # Status
        self.status_label = create_status_label("Select CAN interface and connect")
        layout.addWidget(self.status_label)

    def _on_can_connected(self, base_interface):
        """Handle successful CAN connection from the common widget"""
        # Wrap the base interface with Level 2 capabilities
        self.poco = PocoCANInterfaceLevel2(
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

        # Update the connection widget to use our Level 2 interface for discovery
        self.can_widget.set_poco_interface(self.poco)

        # Set up state synchronization
        self.poco.add_state_callback(self._on_device_state_update)
        self.poco.start_listener()  # Start listening for responses

        # Enable all switches now that we're connected
        for switch in self.switches:
            switch.setEnabled(True)

        self.status_label.setText(f"Connected - Level 2 Protocol Active")

    def _on_can_disconnected(self):
        """Handle CAN disconnection from the common widget"""
        if self.poco:
            self.poco.remove_state_callback(self._on_device_state_update)
            self.poco.disconnect()
            self.poco = None

        # Disable all switches when disconnected
        for switch in self.switches:
            switch.setEnabled(False)

        self.status_label.setText("Disconnected")

    def _on_can_connection_failed(self, error_msg):
        """Handle CAN connection failure from the common widget"""
        self.status_label.setText(f"Connection failed: {error_msg}")

    def _switch_clicked(self, switch):
        """Handle short click - toggle switch"""
        if not self.poco:
            return

        new_state = not switch.is_on
        # Update GUI optimistically but mark as not synced
        switch.set_state(new_state, synced=False)

        # Reset to white color when turning on (mimics real-world light behavior)
        if new_state:  # Turning on
            switch.set_color(0, 0, 100, synced=False)  # Reset to white

        try:
            # Invert the command - if GUI shows on, send off command and vice versa
            if new_state:
                self.poco.turn_off(switch.switch_id)
            else:
                self.poco.turn_on(switch.switch_id)

            # Query state to get confirmation
            self.poco.query_switch_state(switch.switch_id)
            self.status_label.setText(f"Command sent to Switch {switch.switch_id+1}...")
        except Exception as e:
            self.status_label.setText(f"CAN error: {str(e)}")
            # Revert on error
            switch.set_state(not new_state, synced=True)

    def _switch_long_pressed(self, switch):
        """Handle long press - open color wheel"""
        dialog = ColorWheelDialog(self, switch, switch.hue, switch.saturation, switch.brightness)
        dialog.exec_()




    def _on_device_state_update(self, switch_id: int, device_state):
        """
        Called when we receive a state update from the Poco device (thread-safe).
        Emits signal to handle GUI updates on main thread.
        """
        # Emit signal to handle GUI updates on main thread
        self.device_state_signal.emit(switch_id, device_state)

    def _on_device_state_update_safe(self, switch_id: int, device_state):
        """
        Thread-safe GUI update method - runs on main thread.
        Updates the GUI to reflect the actual device state.
        """
        # Find the corresponding switch widget
        if switch_id < len(self.switches):
            switch_widget = self.switches[switch_id]

            # Update the visual state to match device (mark as synced)
            switch_widget.set_state(device_state.is_on, synced=True)

            # Convert device HSB (0-255) to GUI HSB (0-360, 0-100, 0-100)
            gui_hue = int((device_state.hue / 255) * 360)
            gui_sat = int((device_state.saturation / 255) * 100)
            gui_bright = int((device_state.brightness / 255) * 100)

            switch_widget.set_color(gui_hue, gui_sat, gui_bright, synced=True)

            # Update status to show sync
            self.status_label.setText(f"Synced - Switch {switch_id+1}: "
                                    f"{'ON' if device_state.is_on else 'OFF'}")

    def closeEvent(self, event):
        """Clean up when the application is closed"""
        if self.poco:
            self.poco.disconnect()
        event.accept()


def main():
    app = QApplication(sys.argv)

    # Setup logging - change level to control debug output
    from poco_gui_common import setup_logging
    import logging
    setup_logging(logging.INFO)  # Change to logging.DEBUG to see details

    # Set application style
    app.setStyle('Fusion')
    window = VirtualSwitchesGUI()
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
