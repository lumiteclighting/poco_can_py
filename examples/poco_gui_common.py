"""
Poco CAN GUI Common Components
===========================

Shared widgets and utilities for Poco CAN GUI applications.
"""

import os
import logging
import time
from PyQt5.QtCore import Qt, pyqtSignal, QSettings, QTimer
from PyQt5.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
                             QFrame, QComboBox, QCheckBox, QSpinBox, QDialog,
                             QListWidget, QListWidgetItem, QMessageBox)
from PyQt5.QtGui import QFont

from poco_can.poco_can_interface import PocoCANInterfaceBase

# Module logger
logger = logging.getLogger(__name__)

# Note: qRegisterMetaType is no longer needed in modern PyQt5
# Type registration happens automatically for standard Qt types

def setup_logging(level=logging.INFO):
    """
    Setup logging for Poco GUI applications.

    Logging Levels:
    - logging.DEBUG (10): Detailed debug information (rate limiter details, etc.)
    - logging.INFO (20): General information
    - logging.WARNING (30): Warning messages
    - logging.ERROR (40): Error messages
    - logging.CRITICAL (50): Critical errors

    Usage:
        setup_logging(logging.DEBUG)  # Show debug messages
        setup_logging(logging.INFO)   # Hide debug, show info and above (default)
        setup_logging(logging.WARNING) # Only show warnings and errors
    """
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )

    # Set specific loggers to avoid spam from other libraries
    logging.getLogger('poco_can_py').setLevel(level)

class CommandRateLimiter:
    """
    Rate limiter for commands with immediate sending and subsequent rate limiting.

    First command sends immediately. Subsequent commands within the rate limit
    period are queued and sent after the delay (latest command wins).
    Useful for slider controls that generate many rapid events.

    Usage:
        rate_limiter = CommandRateLimiter(delay_ms=100)
        rate_limiter.queue_command(lambda: send_pwm_command(channel, value))
    """

    def __init__(self, delay_ms=100):
        """
        Initialize rate limiter.

        Args:
            delay_ms: Delay between commands in milliseconds
        """
        self.delay_ms = delay_ms
        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._send_queued_command)
        self.queued_command = None
        self.first_command = True
        self.logger = logging.getLogger(f"{__name__}.CommandRateLimiter")

    def queue_command(self, command_func):
        """
        Queue a command to be sent immediately or after rate limit delay.

        If no timer is running, send immediately and start timer.
        If timer is running, queue for delayed sending (latest command wins).

        Args:
            command_func: Callable to execute (should be a lambda or function with no args)
        """
        if not self.timer.isActive():
            # No timer running, send immediately and start timer
            try:
                self.logger.debug(f"Sending command immediately (delay_ms={self.delay_ms})")
                command_func()
            except Exception as e:
                self.logger.error(f"Rate limiter command error: {e}")

            # Start timer to enforce rate limit for next command
            self.logger.debug(f"Starting timer for {self.delay_ms}ms")
            self.timer.start(self.delay_ms)
        else:
            # Timer is running, queue this command (overwrites any existing queued command)
            self.logger.debug(f"Queueing command (timer still active)")
            self.queued_command = command_func

    def _send_queued_command(self):
        """Internal method called when timer expires"""
        self.logger.debug(f"Timer expired (delay was {self.delay_ms}ms)")
        if self.queued_command:
            # Send the queued command
            try:
                self.logger.debug(f"Sending queued command")
                self.queued_command()
            except Exception as e:
                self.logger.error(f"Rate limiter command error: {e}")
            finally:
                self.queued_command = None

            # Restart timer for next rate limit period
            self.logger.debug(f"Restarting timer for {self.delay_ms}ms")
            self.timer.start(self.delay_ms)
        else:
            self.logger.debug(f"No queued command, timer stops")
        # If no queued command, timer stops naturally (don't restart)

    def flush(self):
        """Immediately send any queued command and stop the timer"""
        if self.timer.isActive():
            self.timer.stop()
            self._send_queued_command()


class DeviceDiscoveryDialog(QDialog):
    """
    Dialog for discovering Poco devices on the CAN bus.

    Sends an ENUMERATE_REQUEST broadcast and displays responding devices.
    """

    def __init__(self, poco_interface, parent=None):
        super().__init__(parent)
        self.poco = poco_interface
        self.selected_address = None
        self.discovery_timer = QTimer()
        self.discovery_timer.timeout.connect(self._discovery_timeout)
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle("Discover Poco Devices")
        self.setMinimumWidth(500)
        self.setMinimumHeight(350)

        layout = QVBoxLayout(self)

        # Instructions
        info_label = QLabel("Scanning CAN bus for Poco devices...\n"
                           "Devices will appear below as they respond.")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # Device list
        self.device_list = QListWidget()
        self.device_list.itemDoubleClicked.connect(self._on_device_double_clicked)
        layout.addWidget(self.device_list)

        # Status label
        self.status_label = QLabel("Waiting for responses...")
        layout.addWidget(self.status_label)

        # Buttons
        button_row = QHBoxLayout()

        self.rescan_btn = QPushButton("Rescan")
        self.rescan_btn.clicked.connect(self._start_discovery)
        button_row.addWidget(self.rescan_btn)

        button_row.addStretch()

        self.select_btn = QPushButton("Select Device")
        self.select_btn.clicked.connect(self._on_select_clicked)
        self.select_btn.setEnabled(False)
        button_row.addWidget(self.select_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_row.addWidget(cancel_btn)

        layout.addLayout(button_row)

        # Connect to enumeration callback
        self.poco.add_enumeration_callback(self._on_device_discovered)

        # Start discovery automatically
        QTimer.singleShot(100, self._start_discovery)

    def _start_discovery(self):
        """Start device discovery process."""
        # Clear previous results
        self.device_list.clear()
        self.poco.clear_discovered_devices()
        self.selected_address = None
        self.select_btn.setEnabled(False)
        self.status_label.setText("Scanning... waiting for responses")

        # Send enumerate request
        try:
            self.poco.send_enumerate_request()
            # Wait for responses (3 seconds timeout)
            self.discovery_timer.start(3000)
        except Exception as e:
            self.status_label.setText(f"Error: {e}")
            QMessageBox.critical(self, "Discovery Error", f"Failed to send enumerate request:\n{e}")

    def _discovery_timeout(self):
        """Called when discovery timeout expires."""
        self.discovery_timer.stop()

        device_count = self.device_list.count()
        if device_count == 0:
            self.status_label.setText("No devices found. Check connections and try rescan.")
        else:
            self.status_label.setText(f"Found {device_count} device(s). Double-click to select.")

    def _on_device_discovered(self, can_address, device_info):
        """Called when a device responds to enumeration request."""
        # Create list item with device info
        text = (f"Address: 0x{can_address:02X} ({can_address})  |  "
                f"Device ID: 0x{device_info['device_id']:06X}  |  "
                f"Channels: {device_info['num_channels']}  |  "
                f"Protocol Ver: {device_info['protocol_version']}  |  "
                f"Expander Role: {device_info['expander_role']}")

        item = QListWidgetItem(text)
        item.setData(Qt.UserRole, can_address)  # Store address in item data
        self.device_list.addItem(item)

        # Update status
        self.status_label.setText(f"Found {self.device_list.count()} device(s)...")

        # Enable selection when first device appears
        if self.device_list.count() == 1:
            self.device_list.setCurrentRow(0)
            self.select_btn.setEnabled(True)

    def _on_device_double_clicked(self, item):
        """Handle double-click on device item."""
        self.selected_address = item.data(Qt.UserRole)
        self.accept()

    def _on_select_clicked(self):
        """Handle Select Device button click."""
        current_item = self.device_list.currentItem()
        if current_item:
            self.selected_address = current_item.data(Qt.UserRole)
            self.accept()

    def get_selected_address(self):
        """Get the selected device address."""
        return self.selected_address

    def closeEvent(self, event):
        """Cleanup when dialog closes."""
        self.discovery_timer.stop()
        self.poco.remove_enumeration_callback(self._on_device_discovered)
        super().closeEvent(event)


class CANConnectionWidget(QFrame):
    """
    Rate limiter for commands with immediate sending and subsequent rate limiting.

    First command sends immediately. Subsequent commands within the rate limit
    period are queued and sent after the delay (latest command wins).
    Useful for slider controls that generate many rapid events.

    Usage:
        rate_limiter = CommandRateLimiter(delay_ms=100)
        rate_limiter.queue_command(lambda: send_pwm_command(channel, value))
    """

    def __init__(self, delay_ms=100):
        """
        Initialize rate limiter.

        Args:
            delay_ms: Delay between commands in milliseconds
        """
        self.delay_ms = delay_ms
        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._send_queued_command)
        self.queued_command = None
        self.first_command = True
        self.logger = logging.getLogger(f"{__name__}.CommandRateLimiter")

    def queue_command(self, command_func):
        """
        Queue a command to be sent immediately or after rate limit delay.

        If no timer is running, send immediately and start timer.
        If timer is running, queue for delayed sending (latest command wins).

        Args:
            command_func: Callable to execute (should be a lambda or function with no args)
        """
        if not self.timer.isActive():
            # No timer running, send immediately and start timer
            try:
                self.logger.debug(f"Sending command immediately (delay_ms={self.delay_ms})")
                command_func()
            except Exception as e:
                self.logger.error(f"Rate limiter command error: {e}")

            # Start timer to enforce rate limit for next command
            self.logger.debug(f"Starting timer for {self.delay_ms}ms")
            self.timer.start(self.delay_ms)
        else:
            # Timer is running, queue this command (overwrites any existing queued command)
            self.logger.debug(f"Queueing command (timer still active)")
            self.queued_command = command_func

    def _send_queued_command(self):
        """Internal method called when timer expires"""
        self.logger.debug(f"Timer expired (delay was {self.delay_ms}ms)")
        if self.queued_command:
            # Send the queued command
            try:
                self.logger.debug(f"Sending queued command")
                self.queued_command()
            except Exception as e:
                self.logger.error(f"Rate limiter command error: {e}")
            finally:
                self.queued_command = None

            # Restart timer for next rate limit period
            self.logger.debug(f"Restarting timer for {self.delay_ms}ms")
            self.timer.start(self.delay_ms)
        else:
            self.logger.debug(f"No queued command, timer stops")
        # If no queued command, timer stops naturally (don't restart)

    def flush(self):
        """Immediately send any queued command and stop the timer"""
        if self.timer.isActive():
            self.timer.stop()
            self._send_queued_command()


class CANConnectionWidget(QFrame):
    """
    Reusable CAN connection widget with interface/channel selection.

    Provides a base PocoCANInterfaceBase instance for basic CAN operations.
    Applications should wrap this with their chosen protocol level interface
    if they need protocol-specific methods.

    Signals:
        connected(PocoCANInterfaceBase): Emitted when connection succeeds
        disconnected(): Emitted when disconnection occurs
        connection_failed(str): Emitted when connection fails (error message)
    """

    connected = pyqtSignal(object)  # Emits PocoCANInterface instance
    disconnected = pyqtSignal()
    connection_failed = pyqtSignal(str)

    def __init__(self, settings_org="Lumitec", settings_app="PocoCANApp", parent=None):
        super().__init__(parent)
        self.poco = None
        self.settings = QSettings(settings_org, settings_app)
        self.auto_reconnect = False
        self.reconnect_timer = QTimer()
        self.reconnect_timer.timeout.connect(self._attempt_reconnect)

        # Poco device connection state
        self.device_info = None  # Will contain device_id, num_channels, protocol_version, etc.
        self.last_poll_time = 0
        self.connection_active = False
        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self._poll_poco_device)

        self._setup_ui()
        self._apply_stylesheet()
        self._load_settings()

    def _setup_ui(self):
        self.setFrameStyle(QFrame.NoFrame)
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)

        # CAN Bus Connection Section
        can_group = QFrame()
        can_group.setFrameStyle(QFrame.NoFrame)
        can_group.setObjectName("sectionGroup")
        can_layout = QVBoxLayout(can_group)
        can_layout.setSpacing(8)
        can_layout.setContentsMargins(10, 8, 10, 8)

        # CAN section header
        can_header = QLabel("CAN Bus Connection")
        can_header.setFont(QFont("Arial", 11, QFont.Bold))
        can_header.setObjectName("sectionHeader")
        can_layout.addWidget(can_header)

        # CAN connection row: Interface, Channel, Refresh, Auto-reconnect
        can_row = QHBoxLayout()

        interface_label = QLabel("Interface:")
        interface_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        can_row.addWidget(interface_label)
        self.interface_combo = QComboBox()
        self.interface_combo.addItems(["socketcan", "pcan", "vector"])
        self.interface_combo.setToolTip("CAN interface type")
        can_row.addWidget(self.interface_combo)

        channel_label = QLabel("Channel:")
        channel_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        can_row.addWidget(channel_label)
        self.channel_combo = QComboBox()
        self.channel_combo.setEditable(True)
        self.channel_combo.setToolTip("CAN channel/device name")
        can_row.addWidget(self.channel_combo)

        # Refresh button
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setFixedSize(70, 25)
        self.refresh_btn.setToolTip("Refresh available CAN interfaces")
        self.refresh_btn.clicked.connect(self._refresh_interfaces)
        can_row.addWidget(self.refresh_btn)

        can_layout.addLayout(can_row)

        # CAN controls row: Auto-reconnect, Source Address, Connect button
        can_controls_row = QHBoxLayout()


        source_addr_label = QLabel("Source Address:")
        source_addr_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        can_controls_row.addWidget(source_addr_label)
        self.source_addr_combo = QComboBox()
        self.source_addr_combo.setEditable(True)
        self.source_addr_combo.addItems(["0", "1", "2", "3", "10", "20", "50"])
        self.source_addr_combo.setCurrentText("253")
        self.source_addr_combo.setToolTip("Source address for this GUI (0-253)")
        self.source_addr_combo.setFixedWidth(60)
        can_controls_row.addWidget(self.source_addr_combo)


        auto_reconnect_label = QLabel("Auto-reconnect:")
        auto_reconnect_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        can_controls_row.addWidget(auto_reconnect_label)

        self.auto_reconnect_cb = QCheckBox()
        self.auto_reconnect_cb.setFixedWidth(16)
        self.auto_reconnect_cb.setToolTip("Automatically reconnect if CAN connection is lost")
        self.auto_reconnect_cb.toggled.connect(self._on_auto_reconnect_toggled)
        can_controls_row.addWidget(self.auto_reconnect_cb)

        self.connect_btn = QPushButton("Connect to CAN")
        self.connect_btn.clicked.connect(self._connect_can)
        self.connect_btn.setFixedWidth(150)
        can_controls_row.addWidget(self.connect_btn)

        can_layout.addLayout(can_controls_row)
        main_layout.addWidget(can_group)

        # Poco Device Selection Section (initially hidden)
        self.poco_group = QFrame()
        self.poco_group.setFrameStyle(QFrame.NoFrame)
        self.poco_group.setObjectName("sectionGroup")
        poco_layout = QVBoxLayout(self.poco_group)
        poco_layout.setSpacing(8)
        poco_layout.setContentsMargins(10, 8, 10, 8)

        # Poco section header
        poco_header = QLabel("Poco Device Selection")
        poco_header.setFont(QFont("Arial", 11, QFont.Bold))
        poco_header.setObjectName("sectionHeader")
        poco_layout.addWidget(poco_header)

        # Poco device row: Address selector and Discover button
        poco_row = QHBoxLayout()

        target_device_label = QLabel("Target Device:")
        target_device_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        poco_row.addWidget(target_device_label)
        self.poco_addr_combo = QComboBox()
        self.poco_addr_combo.setEditable(True)
        self.poco_addr_combo.addItems(["0xFF (Broadcast)", "0x21 (33)", "0x82 (130)"])
        self.poco_addr_combo.setCurrentText("0xFF (Broadcast)")
        self.poco_addr_combo.setToolTip("Target Poco device address (0-253: specific device, 255: broadcast)")
        poco_row.addWidget(self.poco_addr_combo)

        self.discover_btn = QPushButton("Discover Devices")
        self.discover_btn.setToolTip("Scan CAN bus for Poco devices")
        self.discover_btn.clicked.connect(self._discover_poco_devices)
        self.discover_btn.setFixedWidth(120)
        poco_row.addWidget(self.discover_btn)

        poco_layout.addLayout(poco_row)

        # Device connection status row
        status_row = QHBoxLayout()

        device_id_label = QLabel("Device ID:")
        device_id_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        status_row.addWidget(device_id_label)

        self.device_id_display = QLabel("Unknown")
        self.device_id_display.setObjectName("deviceIdDisplay")
        self.device_id_display.setMinimumWidth(100)
        status_row.addWidget(self.device_id_display)

        connection_label = QLabel("Status:")
        connection_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        status_row.addWidget(connection_label)

        self.connection_status = QLabel("●")
        self.connection_status.setObjectName("connectionStatus")
        self.connection_status.setProperty("status", "unknown")
        self.connection_status.setToolTip("Connection status: Green=Connected, Red=Disconnected, Gray=Unknown")
        status_row.addWidget(self.connection_status)

        status_row.addStretch()
        poco_layout.addLayout(status_row)

        main_layout.addWidget(self.poco_group)

        # Initially disable the Poco section until CAN is connected
        self.poco_group.setEnabled(False)

    def _apply_stylesheet(self):
        """Apply the consolidated dark theme stylesheet to this widget."""
        self.setStyleSheet(DARK_THEME_STYLESHEET)

    def _load_settings(self):
        """Load saved CAN interface settings."""
        saved_interface = self.settings.value("interface", "socketcan")
        index = self.interface_combo.findText(saved_interface)
        if index >= 0:
            self.interface_combo.setCurrentIndex(index)

        interfaces = self._enumerate_can_interfaces()
        self.channel_combo.addItems(interfaces)

        saved_channel = self.settings.value("channel", "vcan0")
        self.channel_combo.setCurrentText(saved_channel)

        # Load address settings
        saved_source_addr = self.settings.value("source_address", "253")
        self.source_addr_combo.setCurrentText(saved_source_addr)

        saved_poco_addr = self.settings.value("poco_address", "0xFF (Broadcast)")
        self.poco_addr_combo.setCurrentText(saved_poco_addr)

        # Load auto-reconnect setting
        auto_reconnect = self.settings.value("auto_reconnect", False, type=bool)
        self.auto_reconnect_cb.setChecked(auto_reconnect)
        self.auto_reconnect = auto_reconnect

        # Connect signals to save settings when changed
        self.interface_combo.currentTextChanged.connect(self._save_settings)
        self.channel_combo.currentTextChanged.connect(self._save_settings)
        self.source_addr_combo.currentTextChanged.connect(self._save_settings)
        self.poco_addr_combo.currentTextChanged.connect(self._save_settings)

        # Connect signal to update poco_address when dropdown changes
        self.poco_addr_combo.currentTextChanged.connect(self._on_poco_address_changed)

        # Auto-connect if enabled
        if self.auto_reconnect:
            QTimer.singleShot(1000, self._connect_can)  # Connect after 1 second

    def _save_settings(self):
        """Save current CAN interface settings."""
        self.settings.setValue("interface", self.interface_combo.currentText())
        self.settings.setValue("channel", self.channel_combo.currentText())
        self.settings.setValue("source_address", self.source_addr_combo.currentText())
        self.settings.setValue("poco_address", self.poco_addr_combo.currentText())
        self.settings.setValue("auto_reconnect", self.auto_reconnect_cb.isChecked())

    def _on_poco_address_changed(self, text):
        """Update the poco_address in the interface when dropdown changes."""
        if self.poco:
            try:
                new_addr = self._parse_poco_address(text)
                self.poco.poco_address = new_addr
                logging.info(f"Updated target Poco address to: {new_addr}")

                # Do a single poll to check if the new device responds
                self._poll_poco_device()

            except ValueError as e:
                logging.warning(f"Failed to parse Poco address: {e}")

    def _enumerate_can_interfaces(self):
        """Enumerate available CAN interfaces on the system."""
        interfaces = []
        try:
            net_dir = "/sys/class/net"
            if os.path.exists(net_dir):
                for iface in os.listdir(net_dir):
                    if iface.startswith(('can', 'vcan')):
                        interfaces.append(iface)
        except Exception:
            pass
        return interfaces if interfaces else ["can0", "vcan0"]

    def _refresh_interfaces(self):
        """Refresh the list of available CAN interfaces."""
        current_selection = self.channel_combo.currentText()
        self.channel_combo.clear()

        available_interfaces = self._enumerate_can_interfaces()
        self.channel_combo.addItems(available_interfaces)

        # Try to restore previous selection
        if current_selection:
            index = self.channel_combo.findText(current_selection)
            if index >= 0:
                self.channel_combo.setCurrentIndex(index)
            else:
                self.channel_combo.setCurrentText(current_selection)

    def _parse_poco_address(self, text):
        """
        Parse Poco address from combo box text.
        Handles formats like:
        - "0xFF (Broadcast)" -> 255
        - "0x20 - 0x1234" -> 32
        - "255 (Broadcast)" -> 255  (legacy decimal format)
        - "0x20" -> 32
        - "32" -> 32

        Returns:
            int: The parsed address (0-255)
        """
        import re
        text = text.strip()

        # Try to match hex format first (0xNN)
        hex_match = re.match(r'0x([0-9A-Fa-f]+)', text)
        if hex_match:
            return int(hex_match.group(1), 16)

        # Fall back to decimal format
        dec_match = re.match(r'(\d+)', text)
        if dec_match:
            return int(dec_match.group(1))

        raise ValueError(f"Cannot parse address from: {text}")

    def _connect_can(self):
        """Connect to CAN bus."""
        try:
            # Clean up any existing connection first
            if self.poco:
                self.poco.disconnect()
                self.poco = None

            interface = self.interface_combo.currentText()
            channel = self.channel_combo.currentText()

            # Parse source address with validation
            try:
                source_addr = int(self.source_addr_combo.currentText())
                if not (0 <= source_addr <= 253):
                    raise ValueError(f"Source address {source_addr} out of range (0-253)")
            except ValueError as e:
                raise Exception(f"Invalid source address: {e}")

            # Parse poco address with validation
            try:
                poco_addr = self._parse_poco_address(self.poco_addr_combo.currentText())
                if not (0 <= poco_addr <= 255):
                    raise ValueError(f"Poco address {poco_addr} out of range (0-255)")
            except ValueError as e:
                raise Exception(f"Invalid Poco address: {e}")

            # Create base interface - applications can wrap this with their chosen protocol level
            self.poco = PocoCANInterfaceBase(
                interface=interface,
                channel=channel,
                source_address=source_addr,
                poco_address=poco_addr
            )
            self.poco.connect()
            self.poco.start_listener()  # Start listening for enumeration responses

            # Register callback to handle enumerate responses for connection status
            self.poco.add_enumeration_callback(self._on_enumerate_callback)

            # Update UI state for connected CAN bus
            self._set_can_connected_state()

            # Stop reconnect timer if running
            if self.reconnect_timer.isActive():
                self.reconnect_timer.stop()

            self._save_settings()
            self.connected.emit(self.poco)

        except Exception as e:
            self.connection_failed.emit(str(e))
            # Start auto-reconnect if enabled
            if self.auto_reconnect and not self.reconnect_timer.isActive():
                self.reconnect_timer.start(5000)  # Try every 5 seconds

    def _disconnect_can(self):
        """Disconnect from CAN bus."""
        # Emit disconnected signal BEFORE closing the bus so listeners can clean up their notifiers
        self.disconnected.emit()

        if self.poco:
            # Remove our callback before disconnecting
            try:
                self.poco.remove_enumeration_callback(self._on_enumerate_callback)
            except:
                pass  # Ignore errors if callback wasn't registered
            self.poco.disconnect()
            self.poco = None

        # Update UI state for disconnected CAN bus
        self._set_can_disconnected_state()

        # Stop auto-reconnect timer
        if self.reconnect_timer.isActive():
            self.reconnect_timer.stop()

    def _on_auto_reconnect_toggled(self, checked):
        """Handle auto-reconnect checkbox toggle"""
        self.auto_reconnect = checked
        if not checked and self.reconnect_timer.isActive():
            # Stop reconnect timer if auto-reconnect is disabled
            self.reconnect_timer.stop()
        elif checked and not self.poco:
            # Start trying to connect if auto-reconnect is enabled and not connected
            self._connect_can()

        # Save the setting immediately
        self._save_settings()

    def _attempt_reconnect(self):
        """Attempt to reconnect automatically"""
        if not self.poco:  # Only try if not already connected
            self._connect_can()

    def _set_can_connected_state(self):
        """Update UI when CAN bus is connected."""
        # Disable CAN connection controls
        self.interface_combo.setEnabled(False)
        self.channel_combo.setEnabled(False)
        self.refresh_btn.setEnabled(False)
        self.source_addr_combo.setEnabled(False)

        # Update connect button
        self.connect_btn.setText("Disconnect from CAN")
        self.connect_btn.clicked.disconnect()
        self.connect_btn.clicked.connect(self._disconnect_can)

        # Enable Poco device selection section
        self.poco_group.setEnabled(True)

        # Do a single poll on initial connection to check device presence
        self._poll_poco_device()

    def _set_can_disconnected_state(self):
        """Update UI when CAN bus is disconnected."""
        # Stop device polling
        self._stop_device_polling()

        # Re-enable CAN connection controls
        self.interface_combo.setEnabled(True)
        self.channel_combo.setEnabled(True)
        self.refresh_btn.setEnabled(True)
        self.source_addr_combo.setEnabled(True)

        # Update connect button
        self.connect_btn.setText("Connect to CAN")
        self.connect_btn.clicked.disconnect()
        self.connect_btn.clicked.connect(self._connect_can)

        # Disable Poco device selection section
        self.poco_group.setEnabled(False)

    def _discover_poco_devices(self):
        """Discover Poco devices on the CAN bus and populate the address dropdown."""
        if not self.poco:
            QMessageBox.warning(self, "Not Connected",
                              "Please connect to the CAN bus before discovering devices.")
            return

        # Show discovery dialog
        dialog = DeviceDiscoveryDialog(self.poco, self)
        if dialog.exec_() == QDialog.Accepted:
            # User selected a device - update the dropdown with all discovered devices
            devices = self.poco.get_discovered_devices()
            if devices:
                # Remember current selection
                current_text = self.poco_addr_combo.currentText()

                # Clear and repopulate dropdown
                self.poco_addr_combo.clear()

                # Always add broadcast first
                self.poco_addr_combo.addItem("0xFF (Broadcast)")

                # Add discovered devices with formatted text (address in hex and device ID suffix)
                for addr in sorted(devices.keys()):
                    device_info = devices[addr]
                    device_id_suffix = device_info['device_id'] & 0xFFFF  # Last 4 hex digits (16 bits)
                    item_text = f"0x{addr:02X} - 0x{device_id_suffix:04X}"
                    self.poco_addr_combo.addItem(item_text)

                # If user selected a specific device, set it
                selected_addr = dialog.get_selected_address()
                if selected_addr is not None:
                    # Find and select the item with this address
                    for i in range(self.poco_addr_combo.count()):
                        if self.poco_addr_combo.itemText(i).startswith(f"0x{selected_addr:02X} "):
                            self.poco_addr_combo.setCurrentIndex(i)
                            break
                else:
                    # Try to restore previous selection
                    index = self.poco_addr_combo.findText(current_text)
                    if index >= 0:
                        self.poco_addr_combo.setCurrentIndex(index)
                    else:
                        self.poco_addr_combo.setCurrentIndex(0)  # Default to broadcast

                self._save_settings()

    def get_poco_interface(self):
        """Get the current PocoCANInterface instance (or None if not connected)."""
        return self.poco

    def set_poco_interface(self, poco_interface):
        """
        Update the poco interface reference.

        This should be called by application GUIs when they wrap the base interface
        with a higher-level interface (Level 1, Level 2, etc.) so that discovery
        and other operations use the correct interface.

        Args:
            poco_interface: The new interface instance to use
        """
        self.poco = poco_interface

    def is_connected(self):
        """Check if currently connected to CAN bus."""
        return self.poco is not None

    def get_source_address(self):
        """Get the configured source address."""
        try:
            return int(self.source_addr_combo.currentText())
        except ValueError:
            return 0

    def get_poco_address(self):
        """Get the configured Poco target address."""
        try:
            return self._parse_poco_address(self.poco_addr_combo.currentText())
        except ValueError:
            return 255

    def _on_enumerate_callback(self, can_address: int, device_info: dict):
        """Callback for handling enumerate responses from Poco devices."""
        target_addr = self.get_poco_address()

        # If we're targeting this specific device or in broadcast mode
        if target_addr == 0xFF or target_addr == can_address:
            self.device_info = device_info
            self.device_info['can_address'] = can_address

            # Update display
            device_id_hex = f"0x{device_info['device_id']:06X}"
            channels_info = f" ({device_info['num_channels']} ch)"
            self.device_id_display.setText(device_id_hex + channels_info)

            # Mark as connected if this response came recently after our poll
            if time.time() - self.last_poll_time < 2.0:  # Within 2 seconds of poll
                self._update_connection_status(True, "green")
                logger.info(f"Poco device 0x{can_address:02X} responded: {device_id_hex}, {device_info['num_channels']} channels")

    def _start_device_polling(self):
        """
        Start periodic polling of the target Poco device.
        Note: This is only used by the Discover Devices button for active scanning.
        Normal operation does not continuously poll.
        """
        if self.poco and not self.poll_timer.isActive():
            self._update_connection_status(False, "gray")  # Initial unknown state
            self._poll_poco_device()  # Do an immediate poll
            self.poll_timer.start(3000)  # Poll every 3 seconds
            logger.info("Started Poco device polling (discovery mode)")

    def _stop_device_polling(self):
        """Stop periodic polling of the target Poco device."""
        if self.poll_timer.isActive():
            self.poll_timer.stop()
            logger.info("Stopped Poco device polling")
        self._update_connection_status(False, "gray")
        self.device_info = None

    def _poll_poco_device(self):
        """Send an enumerate request to check if the target device is still responsive."""
        if not self.poco:
            return

        try:
            target_addr = self.get_poco_address()

            # Track when we sent the poll
            self.last_poll_time = time.time()

            # Send enumerate request using the interface's built-in method
            self.poco.send_enumerate_request(priority=6)

            # For broadcast address, we consider the poll successful if we can send
            if target_addr == 0xFF:
                self.device_id_display.setText("Broadcast Mode")
                # Don't immediately mark as green - wait for actual response

            # For specific addresses, wait for response
            # Response handling is done via the callback we registered

        except Exception as e:
            logger.error(f"Error during device polling: {e}")
            self._update_connection_status(False, "red")

    def _update_connection_status(self, connected: bool, color: str):
        """Update the visual connection status indicator."""
        self.connection_active = connected

        if color == "green":
            self.connection_status.setProperty("status", "connected")
            self.connection_status.setToolTip("Connected to Poco device")
        elif color == "red":
            self.connection_status.setProperty("status", "disconnected")
            self.connection_status.setToolTip("Poco device not responding")
        else:  # gray
            self.connection_status.setProperty("status", "unknown")
            self.connection_status.setToolTip("Connection status unknown")

        # Force style refresh
        self.connection_status.style().unpolish(self.connection_status)
        self.connection_status.style().polish(self.connection_status)

    def cleanup(self):
        """Clean up resources - should be called before widget destruction"""
        self._stop_device_polling()
        if self.reconnect_timer.isActive():
            self.reconnect_timer.stop()
        if self.poco:
            self.poco.disconnect()
            self.poco = None


# Common dark theme stylesheet
DARK_THEME_STYLESHEET = """
    QMainWindow {
        background-color: #1a1a1a;
    }
    QWidget {
        background-color: #1a1a1a;
        color: #ffffff;
    }
    QComboBox, QLineEdit, QSpinBox {
        background-color: #404040;
        border: 1px solid #606060;
        border-radius: 4px;
        padding: 4px 8px;
        color: #ffffff;
    }
    QComboBox:disabled, QLineEdit:disabled, QSpinBox:disabled {
        background-color: #2a2a2a;
        color: #888888;
        border: 1px solid #404040;
    }
    QPushButton {
        background-color: #404040;
        border: 1px solid #606060;
        border-radius: 6px;
        padding: 6px 12px;
        color: #ffffff;
    }
    QPushButton:hover {
        background-color: #505050;
    }
    QPushButton:pressed {
        background-color: #353535;
    }
    QPushButton:disabled {
        background-color: #2a2a2a;
        color: #666666;
        border: 1px solid #404040;
    }
    QCheckBox:disabled {
        color: #666666;
    }
    QLabel {
        border: none !important;
        background-color: transparent !important;
        color: #ffffff;
    }

    /* Section Headers */
    QLabel[objectName="sectionHeader"] {
        color: #cccccc;
        border: none;
        font-weight: bold;
    }

    /* Device ID Display */
    QLabel[objectName="deviceIdDisplay"] {
        font-family: monospace;
    }

    /* Connection Status Indicator */
    QLabel[objectName="connectionStatus"] {
        font-size: 16px;
    }
    QLabel[objectName="connectionStatus"][status="connected"] {
        color: #00ff00;
    }
    QLabel[objectName="connectionStatus"][status="disconnected"] {
        color: #ff0000;
    }
    QLabel[objectName="connectionStatus"][status="unknown"] {
        color: #808080;
    }

    /* Section Group Frames */
    QFrame[objectName="sectionGroup"] {
        background-color: #2a2a2a;
        border: 1px solid #404040;
        border-radius: 6px;
    }

    QGroupBox {
        border: 1px solid #606060;
        border-radius: 8px;
        margin-top: 10px;
        padding-top: 10px;
        color: #ffffff;
        font-weight: bold;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 5px 0 5px;
    }
    QFrame[frameShape="4"] {
        background-color: #606060;
        max-height: 1px;
    }
"""


def create_title_label(text, font_size=20):
    """Create a styled title label."""
    label = QLabel(text)
    label.setAlignment(Qt.AlignCenter)
    label.setFont(QFont("Arial", font_size, QFont.Bold))
    return label


def create_status_label(text="Not connected", font_size=11):
    """Create a styled status label."""
    label = QLabel(text)
    label.setAlignment(Qt.AlignCenter)
    label.setFont(QFont("Arial", font_size))
    return label
