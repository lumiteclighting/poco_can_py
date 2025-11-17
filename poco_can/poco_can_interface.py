"""
Poco CAN Bus Interface - Cross-Platform CAN Abstraction
========================================================

This module provides a cross-platform CAN bus interface for the Poco protocol.
It supports:
- Linux: SocketCAN
- Windows: PCAN, IXXAT, Vector, etc. via python-can
- macOS: USB CAN adapters via python-can

Device Targeting:
- Each PocoCANInterface targets one device address (set at initialization)
- Use poco_address=0xFF for broadcast (all devices)
- Use poco_address=0-253 for specific devices
- Create multiple interface instances to control multiple specific devices

Dependencies:
    pip install python-can

For SocketCAN on Linux:
    sudo ip link set can0 type can bitrate 250000
    sudo ip link set can0 up
"""

import can
import logging
from typing import Optional, Callable
from poco_can.poco_can_protocol import *


logger = logging.getLogger(__name__)


class PocoCANInterfaceBase:
    """
    Base class for Poco CAN interfaces - provides common CAN bus functionality.

    This class handles the low-level CAN communication but should not be used directly.
    Use one of the protocol-level interfaces instead:
    - PocoCANInterfaceLevel0: Output Channel Control
    - PocoCANInterfaceLevel1: Binary Switch Bank Control
    - PocoCANInterfaceLevel2: Proprietary VSw Actions

    Device Targeting:
        Each interface instance targets a specific device or broadcasts to all devices.
        The target is set once during initialization and used for all subsequent
        method calls. To control multiple specific devices, create multiple
        interface instances.
    """

    def __init__(self,
                 interface: str = 'socketcan',
                 channel: str = 'can0',
                 bitrate: int = 250000,
                 poco_address: int = 0xFF,
                 source_address: int = 253):
        """
        Initialize CAN interface.

        Args:
            interface: CAN interface type ('socketcan', 'pcan', 'vector', etc.)
            channel: Channel name ('can0', 'PCAN_USBBUS1', etc.)
            bitrate: CAN bitrate (250000 for NMEA2000)
            poco_address: Target Poco device address. ALL methods will send
                         commands to this address. Use 0xFF for broadcast
                         (all devices) or 0-253 for specific device.
            source_address: Our source address (0-253)

        Note:
            The poco_address cannot be changed after initialization. To control
            multiple specific devices, create separate interface instances for
            each target device.
        """
        self.interface = interface
        self.channel = channel
        self.bitrate = bitrate
        self.poco_address = poco_address
        self.source_address = source_address
        self.bus: Optional[can.Bus] = None
        self.notifier: Optional[can.Notifier] = None

        # State management
        self.switch_states: dict = {}  # switch_id -> SwitchState
        self.state_callbacks: list = []  # Functions to call on state updates

        # Device enumeration
        self.discovered_devices: dict = {}  # can_addr -> device_info dict
        self.enumeration_callbacks: list = []  # Functions to call on device discovery

    def connect(self):
        """Establish CAN bus connection."""
        try:
            # Create bus instance
            if self.interface == 'socketcan':
                # Linux SocketCAN
                self.bus = can.Bus(
                    interface=self.interface,
                    channel=self.channel,
                    bitrate=self.bitrate
                )
            else:
                # Other interfaces (Windows/macOS)
                self.bus = can.Bus(
                    interface=self.interface,
                    channel=self.channel,
                    bitrate=self.bitrate
                )

            logger.info(f"Connected to CAN bus: {self.interface}/{self.channel} @ {self.bitrate} bps")

        except Exception as e:
            logger.error(f"Failed to connect to CAN bus: {e}")
            raise

    def disconnect(self):
        """Close CAN bus connection."""
        if self.notifier:
            self.notifier.stop()
            self.notifier = None

        if self.bus:
            self.bus.shutdown()
            self.bus = None
            logger.info("Disconnected from CAN bus")

    def send_raw(self, can_id: int, data: bytes, priority: int = 3):
        """
        Send raw CAN message.

        Args:
            can_id: CAN arbitration ID (29-bit extended)
            data: Message data (up to 8 bytes)
            priority: Message priority (0-7)
        """
        if not self.bus:
            raise RuntimeError("CAN bus not connected")

        msg = can.Message(
            arbitration_id=can_id,
            data=data,
            is_extended_id=True
        )

        try:
            self.bus.send(msg)
            logger.debug(f"Sent: ID=0x{can_id:08X} Data={data.hex(' ')}")
        except can.CanError as e:
            logger.error(f"Failed to send message: {e}")
            raise

    def send_proprietary(self, data: bytes, priority: int = 3):
        """
        Send proprietary PGN 61184 message to Poco.

        Args:
            data: 8-byte message data (already encoded)
            priority: Message priority (0-7)
        """
        can_id = calculate_pgn_can_id(
            PGN_PROPRIETARY_SINGLE_FRAME,
            priority,
            self.source_address,
            self.poco_address
        )
        self.send_raw(can_id, data, priority)

    # Base functionality for state management and monitoring

    def add_state_callback(self, callback: Callable):
        """
        Add a callback function to be called when switch state updates are received.

        Args:
            callback: Function that takes (switch_id, SwitchState) as arguments
        """
        if callback not in self.state_callbacks:
            self.state_callbacks.append(callback)

    def remove_state_callback(self, callback: Callable):
        """Remove a state update callback."""
        if callback in self.state_callbacks:
            self.state_callbacks.remove(callback)

    def get_switch_state(self, switch_id: int) -> Optional['SwitchState']:
        """
        Get the last known state of a switch.

        Args:
            switch_id: Switch ID (0-31)

        Returns:
            SwitchState object or None if no state known
        """
        return self.switch_states.get(switch_id)

    def add_enumeration_callback(self, callback: Callable):
        """
        Add a callback function to be called when devices are discovered.

        Args:
            callback: Function that takes (can_address, device_info) as arguments
                     device_info is dict with keys: device_id, num_channels,
                     protocol_version, expander_role
        """
        if callback not in self.enumeration_callbacks:
            self.enumeration_callbacks.append(callback)

    def remove_enumeration_callback(self, callback: Callable):
        """Remove a device enumeration callback."""
        if callback in self.enumeration_callbacks:
            self.enumeration_callbacks.remove(callback)

    def send_enumerate_request(self, priority: int = 6):
        """
        Send an enumeration request to discover Poco devices on the network.

        This broadcasts a request to all devices. Devices will respond with
        ENUMERATE_RESPONSE containing their device ID and capabilities.

        Args:
            priority: Message priority (default 6 for discovery)
        """
        can_id, data = create_enumerate_request_message(
            src_addr=self.source_address,
            dest_addr=0xFF  # Broadcast
        )
        self.send_raw(can_id, data, priority)
        logger.debug("Sent enumerate request (broadcast)")

    def get_discovered_devices(self) -> dict:
        """
        Get the list of discovered devices.

        Returns:
            Dict mapping CAN address -> device_info dict
            device_info contains: device_id, num_channels, protocol_version, expander_role
        """
        return self.discovered_devices.copy()

    def clear_discovered_devices(self):
        """Clear the list of discovered devices."""
        self.discovered_devices.clear()
        logger.debug("Cleared discovered devices list")

    def _handle_message(self, msg: can.Message):
        """Internal message handler wrapper with exception handling."""
        try:
            self._handle_message_impl(msg)
        except Exception as e:
            logger.error(f"Exception in _handle_message: {e}", exc_info=True)

    def _handle_message_impl(self, msg: can.Message):
        """Internal message handler implementation."""
        # Extract PGN and source address from CAN ID
        raw_pgn = ((msg.arbitration_id >> 8) & 0x3FFFF)
        src_addr = msg.arbitration_id & 0xFF

        # For PDU1 format (PF < 240), the PS byte is destination address, not part of PGN
        # Normalize PGN by masking out PS byte for PDU1 to get the actual PGN
        pdu_format = (raw_pgn >> 8) & 0xFF
        if pdu_format < 240:
            # PDU1 - mask out PS byte (destination address)
            pgn = raw_pgn & 0xFF00
        else:
            # PDU2 - PS is group extension, part of PGN
            pgn = raw_pgn

        # Filter messages: only process if from our target device (or if we're broadcasting, accept from anyone)
        if self.poco_address != 0xFF and src_addr != self.poco_address:
            # Special case: always accept ENUMERATE_RESPONSE regardless of target
            if pgn == PGN_PROPRIETARY_SINGLE_FRAME and len(msg.data) >= 3:
                pid = msg.data[2]
                if pid != ProprietaryID.ENUMERATE_RESPONSE:
                    return  # Ignore messages from other devices
            else:
                return  # Ignore non-proprietary or non-enumeration messages from other devices

        if pgn == PGN_PROPRIETARY_SINGLE_FRAME and len(msg.data) >= 8:
            # Check PID to determine message type
            pid = msg.data[2]

            if pid == ProprietaryID.ENUMERATE_RESPONSE:
                # Decode enumerate response
                device_info = decode_enumerate_response(msg.data)
                if device_info:
                    # Store device info with CAN address
                    self.discovered_devices[src_addr] = {
                        'can_address': src_addr,
                        **device_info
                    }

                    # Notify callbacks
                    for callback in self.enumeration_callbacks:
                        try:
                            callback(src_addr, device_info)
                        except Exception as e:
                            logger.warning(f"Enumeration callback error: {e}")

                    logger.info(f"Discovered device at 0x{src_addr:02X}: "
                              f"ID=0x{device_info['device_id']:06X} "
                              f"Ch={device_info['num_channels']} "
                              f"ProtVer={device_info['protocol_version']} "
                              f"ExpanderRole={device_info['expander_role']}")

            elif pid == ProprietaryID.VSW_STATE:
                # Try to decode as state response
                state = decode_vsw_state_response(msg.data)
                if state:
                    # Update our cached state
                    self.switch_states[state.switch_id] = state

                    # Notify callbacks
                    for callback in self.state_callbacks:
                        try:
                            callback(state.switch_id, state)
                        except Exception as e:
                            logger.warning(f"State callback error: {e}")

                    logger.debug(f"Updated state for switch {state.switch_id}: "
                               f"on={state.is_on} H={state.hue} S={state.saturation} B={state.brightness}")

        # Also call proprietary message handler for subclasses
        if pgn == PGN_PROPRIETARY_SINGLE_FRAME:
            src_addr = msg.arbitration_id & 0xFF
            self._handle_proprietary_message(pgn, msg.data, src_addr)

    def _handle_proprietary_message(self, pgn: int, data: bytes, src_addr: int):
        """
        Handle proprietary messages - can be overridden by subclasses.
        Base implementation does nothing.
        """
        pass

    def start_listener(self, callback: Optional[Callable[[can.Message], None]] = None):
        """
        Start listening for CAN messages.

        Args:
            callback: Optional function to call for each received message
        """
        if not self.bus:
            raise RuntimeError("CAN bus not connected")

        # If a notifier already exists, stop it first to avoid conflicts
        if self.notifier:
            logger.debug("Stopping existing notifier before creating new one")
            self.notifier.stop()
            self.notifier = None

        # Always include our internal handler
        listeners = [self._handle_message]
        if callback:
            listeners.append(callback)

        # Create notifier
        self.notifier = can.Notifier(self.bus, listeners)
        logger.info("Started CAN message listener")

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()


# Protocol Level Classes

class PocoCANInterfaceLevel0(PocoCANInterfaceBase):
    """
    Level 0: Output Channel Control (PGN 61184 PIDs)

    Low-level direct channel control using proprietary PIDs.
    Use for applications that need direct hardware channel control.

    Examples:
        poco = PocoCANInterfaceLevel0()
        poco.connect()
        poco.send_pli_raw(channel=0, red=255, green=0, blue=0)
        poco.send_pwm_channel(channel=1, duty_cycle=50)
        poco.send_binary_channel(channel=2, state=True)
    """

    def send_pli_raw(self, channel: int, pli_message: int, priority: int = 3):
        """
        Send PLI Raw command.

        Args:
            channel: Output channel (0-255)
            pli_message: Raw PLI message value (0-0xFFFFFF)
            priority: CAN priority (0-7)
        """
        data = encode_outch_pli_raw(channel, pli_message)
        self.send_proprietary(data, priority)
        logger.info(f"PLI Raw Ch{channel}: 0x{pli_message:06X}")

    def send_pli_t2hsb(self, channel: int, hue: int, saturation: int, brightness: int,
                      pli_clan: int = 0, transition: int = 0, priority: int = 3):
        """
        Send PLI T2HSB command.

        Args:
            channel: Output channel (1-4, will be clamped)
            hue: Hue (0-255: 0=Red, 85=Green, 170=Blue, 255=close to Red)
            saturation: Saturation (0-15)
            brightness: Brightness (0-15)
            pli_clan: PLI clan identifier (0-63)
            transition: Transition mode (0-7)
            priority: CAN priority (0-7)
        """
        data = encode_outch_pli_t2hsb(channel, hue, saturation, brightness, pli_clan, transition)
        self.send_proprietary(data, priority)
        logger.info(f"PLI T2HSB Ch{channel}: Clan={pli_clan} Trans={transition} H={hue} S={saturation} B={brightness}")

    def send_pli_t2rgb(self, channel: int, red: int, green: int, blue: int,
                      pli_clan: int = 0, transition: int = 0, priority: int = 3):
        """
        Send PLI T2RGB command (5-bit RGB).

        Args:
            channel: Output channel (1-4, will be clamped)
            red: Red intensity (0-255, will be scaled to 0-31 for protocol)
            green: Green intensity (0-255, will be scaled to 0-31 for protocol)
            blue: Blue intensity (0-255, will be scaled to 0-31 for protocol)
            pli_clan: PLI clan identifier (0-63)
            transition: Transition mode (0-7)
            priority: CAN priority (0-7)
        """
        data = encode_outch_pli_t2rgb(channel, red, green, blue, pli_clan, transition)
        self.send_proprietary(data, priority)
        logger.info(f"PLI T2RGB Ch{channel}: Clan={pli_clan} Trans={transition} R={red} G={green} B={blue}")

    def send_pli_t2hs(self, channel: int, hue: int, saturation: int,
                     pli_clan: int = 0, transition: int = 0, priority: int = 3):
        """
        Send PLI T2HS command (Hue/Saturation only, no brightness change).

        Args:
            channel: Output channel (1-4, will be clamped)
            hue: Hue (0-255: 0=Red, 85=Green, 170=Blue, 255=close to Red)
            saturation: Saturation (0-15: 0=White, 15=Fully saturated)
            pli_clan: PLI clan identifier (0-63)
            transition: Transition mode (0-7)
            priority: CAN priority (0-7)
        """
        data = encode_outch_pli_t2hs(channel, hue, saturation, pli_clan, transition)
        self.send_proprietary(data, priority)
        logger.info(f"PLI T2HS Ch{channel}: Clan={pli_clan} Trans={transition} H={hue} S={saturation}")

    def send_pli_t2b(self, channel: int, brightness: int,
                    pli_clan: int = 0, transition: int = 0, priority: int = 3):
        """
        Send PLI T2B command (Brightness only, no color change).

        Args:
            channel: Output channel (1-4, will be clamped)
            brightness: Brightness level (0-255: 0=Off, 255=Full bright)
            pli_clan: PLI clan identifier (0-63)
            transition: Transition mode (0-7)
            priority: CAN priority (0-7)
        """
        data = encode_outch_pli_t2b(channel, brightness, pli_clan, transition)
        self.send_proprietary(data, priority)
        logger.info(f"PLI T2B Ch{channel}: Clan={pli_clan} Trans={transition} B={brightness}")

    def send_pli_t2bd(self, channel: int, delta: int,
                     pli_clan: int = 0, transition: int = 0, priority: int = 3):
        """
        Send PLI T2BD command (Brightness Delta - relative change).

        Args:
            channel: Output channel (1-4, will be clamped)
            delta: Brightness delta (-127 to +127: negative=dimmer, positive=brighter)
            pli_clan: PLI clan identifier (0-63)
            transition: Transition mode (0-7)
            priority: CAN priority (0-7)
        """
        data = encode_outch_pli_t2bd(channel, delta, pli_clan, transition)
        self.send_proprietary(data, priority)
        logger.info(f"PLI T2BD Ch{channel}: Clan={pli_clan} Trans={transition} Delta={delta:+d}")

    def send_pli_t2p(self, channel: int, pattern: int,
                    pli_clan: int = 0, transition: int = 0, priority: int = 3):
        """
        Send PLI T2P command (Pattern selection).

        Args:
            channel: Output channel (1-4, will be clamped)
            pattern: Pattern ID (0-253: see pattern table)
            pli_clan: PLI clan identifier (0-63)
            transition: Transition mode (0-7)
            priority: CAN priority (0-7)
        """
        data = encode_outch_pli_t2p(channel, pattern, pli_clan, transition)
        self.send_proprietary(data, priority)
        logger.info(f"PLI T2P Ch{channel}: Clan={pli_clan} Trans={transition} Pattern={pattern}")

    def request_channel_status(self, channel: int = 0, priority: int = 3):
        """
        Request current status of output channel(s).

        Device will respond with OUTPUTCH_STATUS (PID 32) message(s).

        Args:
            channel: Output channel (1-4) or 0 for all channels (default: 0)
            priority: CAN priority (0-7)
        """
        from poco_can.poco_can_protocol import encode_outch_status_request

        data = encode_outch_status_request(channel)
        self.send_proprietary(data, priority)
        if channel == 0:
            logger.info(f"Requesting status for all channels")
        else:
            logger.info(f"Requesting status for channel {channel}")

    def send_vsw_rgb(self, switch_id: int, red: int, green: int, blue: int, priority: int = 3):
        """
        Send Virtual Switch RGB color command.

        RGB values are converted to HSB internally by Poco firmware.

        Args:
            switch_id: Virtual switch ID (0-31)
            red: Red component (0-255)
            green: Green component (0-255)
            blue: Blue component (0-255)
            priority: CAN priority (0-7)
        """
        from poco_can.poco_can_protocol import encode_vsw_custom_rgb

        data = encode_vsw_custom_rgb(switch_id, red, green, blue)
        self.send_proprietary(data, priority)
        logger.info(f"VSw RGB Switch{switch_id}: R={red} G={green} B={blue}")

    def send_pwm_channel(self, channel: int, duty_cycle: int, priority: int = 3):
        """
        Send PWM Channel command.

        Args:
            channel: Output channel (0-255)
            duty_cycle: PWM duty cycle (0-255, where 255 = 100%)
            priority: CAN priority (0-7)
        """
        data = encode_outch_pwm_channel(channel, duty_cycle)
        self.send_proprietary(data, priority)
        logger.info(f"PWM Ch{channel}: {duty_cycle/255*100:.1f}%")

    def send_binary_channel(self, channel: int, state: bool, priority: int = 3):
        """
        Send Binary Channel command.

        Args:
            channel: Output channel (0-255)
            state: True for ON, False for OFF
            priority: CAN priority (0-7)
        """
        data = encode_outch_binary_channel(channel, 1 if state else 0)
        self.send_proprietary(data, priority)
        logger.info(f"Binary Ch{channel}: {'ON' if state else 'OFF'}")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Level 0 specific state management
        self.channel_status_callbacks: list = []  # Functions to call on channel status updates

    def add_channel_status_callback(self, callback: Callable):
        """
        Add a callback function for channel status updates.

        The callback will be called with: callback(channel, mode, output_level, input_voltage_mv, current_ma)

        Args:
            callback: Function to call when channel status is received
        """
        if callback not in self.channel_status_callbacks:
            self.channel_status_callbacks.append(callback)

    def remove_channel_status_callback(self, callback: Callable):
        """Remove a channel status callback."""
        if callback in self.channel_status_callbacks:
            self.channel_status_callbacks.remove(callback)

    def _handle_proprietary_message(self, pgn: int, data: bytes, src_addr: int):
        """Handle incoming proprietary messages - override from base class."""
        super()._handle_proprietary_message(pgn, data, src_addr)

        if len(data) >= 3:
            # Check if this is a status message
            pid = data[2]  # Third byte is PID
            if pid == ProprietaryID.OUTPUTCH_STATUS:
                try:
                    status = decode_outch_status(data)
                    # Call all registered callbacks
                    for callback in self.channel_status_callbacks:
                        try:
                            callback(
                                status['channel'],
                                status['mode'],
                                status['output_level'],
                                status['input_voltage_mv'],
                                status['current_ma']
                            )
                        except Exception as e:
                            logger.error(f"Channel status callback error: {e}")
                except Exception as e:
                    logger.error(f"Failed to decode channel status: {e}")


class PocoCANInterfaceLevel1(PocoCANInterfaceBase):
    """
    Level 1: Binary Switch Bank Control (PGN 127501/127502)

    Uses standard NMEA2000 Binary Switch Bank messages for compatibility
    with other marine electronics. Each bank controls up to 28 switches.

    Examples:
        poco = PocoCANInterfaceLevel1()
        poco.connect()
        poco.set_switch_bank(bank=0, switches={0: True, 1: False, 2: True})
        poco.query_switch_bank(bank=0)
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Level 1 specific state management
        self.binary_callbacks: list = []  # Functions to call on binary switch updates
        self.binary_switch_states: dict = {}  # bank -> list of switch states

    def set_switch_bank(self, bank: int, switches: dict, priority: int = 3):
        """
        Control switches in a binary switch bank.

        Args:
            bank: Bank/Instance number (0-255)
            switches: Dict of {switch_id: state} where switch_id is 0-27
                     and state is True/False/None (None = no change)
            priority: CAN priority (0-7)
        """
        # Convert dict to list format
        switch_states = [3] * 28  # Default to "no change"
        for switch_id, state in switches.items():
            if 0 <= switch_id <= 27:
                if state is True:
                    switch_states[switch_id] = 1
                elif state is False:
                    switch_states[switch_id] = 0
                # None or any other value leaves as 3 (no change)

        self.send_binary_switch_control(bank, switch_states, priority)

        active_switches = {k: v for k, v in switches.items() if v is not None}
        logger.info(f"Binary switch bank {bank}: {active_switches}")

    def query_switch_bank(self, bank: int, priority: int = 3):
        """
        Query the status of a binary switch bank.

        Args:
            bank: Bank/Instance number to query
            priority: CAN priority (0-7)
        """
        # Send PGN 127501 (Binary Switch Bank Status) query
        can_id = calculate_pgn_can_id(
            PGN_BINARY_SWITCH_STATUS,
            priority,
            self.source_address,
            self.poco_address
        )
        # Query message - just the bank number
        data = bytes([bank] + [0xFF] * 7)
        self.send_raw(can_id, data, priority)
        logger.debug(f"Queried binary switch bank {bank}")

    def send_binary_switch_control(self, bank: int, switch_states: list):
        """
        Send Binary Switch Bank Control (PGN 127502) - Low-level method.

        For higher-level control, prefer using set_switch_bank().

        Args:
            bank: Bank/Instance number
            switch_states: List of states (0=Off, 1=On, 3=NoChange) for up to 28 switches
        """
        can_id = calculate_pgn_can_id(
            PGN_BINARY_SWITCH_CONTROL,
            3,  # priority
            self.source_address,
            self.poco_address
        )
        data = encode_binary_switch_control(bank, switch_states)
        self.send_raw(can_id, data)
        logger.info(f"Sent binary switch control for bank {bank}")

    def add_binary_callback(self, callback: Callable):
        """
        Add a callback function for binary switch status updates.

        Args:
            callback: Function that takes (bank, switch_states) where switch_states
                     is a list of 28 states (0=Off, 1=On, 3=N/A)
        """
        if callback not in self.binary_callbacks:
            self.binary_callbacks.append(callback)

    def remove_binary_callback(self, callback: Callable):
        """Remove a binary switch status callback."""
        if callback in self.binary_callbacks:
            self.binary_callbacks.remove(callback)

    def _handle_message(self, msg: can.Message):
        """Level 1 message handler that processes binary switch responses and calls base handler."""
        # First call base class handler for general message processing
        super()._handle_message(msg)

        # Extract PGN from CAN ID
        pgn = ((msg.arbitration_id >> 8) & 0x3FFFF)

        # Handle Level 1 specific messages
        if pgn == PGN_BINARY_SWITCH_STATUS:
            self._decode_binary_status(msg.data)

    def _decode_binary_status(self, data: bytes):
        """Decode binary switch bank status and notify callbacks."""
        if len(data) < 1:
            return

        bank = data[0]
        switch_states = []

        # Decode all 28 switch states
        for i in range(28):
            byte_idx = 1 + (i // 4)
            if byte_idx >= len(data):
                switch_states.append(3)  # N/A if data not available
                continue
            bit_offset = (i % 4) * 2
            state = (data[byte_idx] >> bit_offset) & 0x03
            switch_states.append(state)

        # Store in cache
        self.binary_switch_states[bank] = switch_states

        # Notify callbacks
        for callback in self.binary_callbacks:
            try:
                callback(bank, switch_states)
            except Exception as e:
                logger.warning(f"Binary callback error: {e}")

        logger.debug(f"Updated binary switch status for bank {bank}: "
                    f"{sum(1 for s in switch_states[:10] if s == 1)}/10 switches on")


class PocoCANInterfaceLevel2(PocoCANInterfaceBase):
    """
    Level 2: Proprietary VSw Actions (PGN 61184 PIDs)

    High-level virtual switch control with colors, PocoFxs, and dimming.
    This is the most feature-rich interface for Poco lighting control.

    Examples:
        poco = PocoCANInterfaceLevel2()
        poco.connect()
        poco.turn_on(switch_id=0)
        poco.set_color(switch_id=1, hue=85, saturation=255, brightness=200)
        poco.start_pocofx(switch_id=2, pocofx_id=5)
    """

    def __init__(self, *args, **kwargs):
        """Initialize Level 2 interface - calls base class initialization."""
        super().__init__(*args, **kwargs)

    def turn_on(self, switch_id: int):
        """Turn on a switch."""
        _, data = create_vsw_turn_on_message(switch_id, self.source_address, self.poco_address)
        self.send_proprietary(data)
        logger.info(f"Turned ON switch {switch_id}")

    def turn_off(self, switch_id: int):
        """Turn off a switch."""
        _, data = create_vsw_turn_off_message(switch_id, self.source_address, self.poco_address)
        self.send_proprietary(data)
        logger.info(f"Turned OFF switch {switch_id}")

    def toggle(self, switch_id: int):
        """Toggle a switch on/off."""
        data = encode_vsw_simple_action(switch_id, VSwAction.TOGGLE)
        self.send_proprietary(data)
        logger.info(f"Toggled switch {switch_id}")

    def dim_up(self, switch_id: int):
        """Increase brightness by 10%."""
        data = encode_vsw_simple_action(switch_id, VSwAction.DIM_UP)
        self.send_proprietary(data)
        logger.info(f"Dimmed UP switch {switch_id}")

    def dim_down(self, switch_id: int):
        """Decrease brightness by 10%."""
        data = encode_vsw_simple_action(switch_id, VSwAction.DIM_DOWN)
        self.send_proprietary(data)
        logger.info(f"Dimmed DOWN switch {switch_id}")

    def delta_brightness(self, switch_id: int, delta: int):
        """
        Apply brightness delta to a switch.

        Args:
            switch_id: Switch to control (0-31)
            delta: Brightness delta (-128 to +127, where 1 = ~0.79% brightness change)
        """
        from poco_can.poco_can_protocol import encode_vsw_delta_brightness

        if not -128 <= delta <= 127:
            raise ValueError(f"Delta must be between -128 and 127, got {delta}")

        data = encode_vsw_delta_brightness(switch_id, delta)
        self.send_proprietary(data)
        logger.info(f"Applied brightness delta {delta} to switch {switch_id}")

    def set_color(self, switch_id: int, hue: int, saturation: int, brightness: int):
        """
        Set switch color and brightness.

        Args:
            switch_id: Switch to control (0-31)
            hue: 0-255 (0=Red, 85=Green, 170=Blue, 255≈Red)
            saturation: 0-255 (0=White, 255=Fully saturated)
            brightness: 0-255 (0=Off, 255=Full brightness)
        """
        data = encode_vsw_hsb(
            switch_id, HSBAction.T2HSB, hue, saturation, brightness
        )
        self.send_proprietary(data)
        logger.info(f"Set switch {switch_id} to H={hue} S={saturation} B={brightness}")

    def set_color_preset(self, switch_id: int, color_name: str, brightness: int = 255):
        """
        Set switch to a preset color.

        Args:
            switch_id: Switch to control (0-31)
            color_name: 'red', 'green', 'blue', 'cyan', 'magenta', 'yellow', 'white'
            brightness: 0-255 (0=Off, 255=Full brightness)
        """
        colors = {
            'red': (0, 255),
            'green': (85, 255),
            'blue': (170, 255),
            'cyan': (127, 255),
            'magenta': (212, 255),
            'yellow': (42, 255),
            'white': (0, 0),
        }

        if color_name.lower() not in colors:
            raise ValueError(f"Unknown color: {color_name}. Use: {list(colors.keys())}")

        hue, sat = colors[color_name.lower()]
        self.set_color(switch_id, hue, sat, brightness)

    def send_vsw_rgb(self, switch_id: int, red: int, green: int, blue: int, priority: int = 3):
        """
        Send Virtual Switch RGB color command.

        RGB values are converted to HSB internally by Poco firmware.

        Args:
            switch_id: Virtual switch ID (0-31)
            red: Red component (0-255)
            green: Green component (0-255)
            blue: Blue component (0-255)
            priority: CAN priority (0-7)
        """
        from poco_can.poco_can_protocol import encode_vsw_custom_rgb

        data = encode_vsw_custom_rgb(switch_id, red, green, blue)
        self.send_proprietary(data, priority)
        logger.info(f"VSw RGB Switch{switch_id}: R={red} G={green} B={blue}")

    def start_pocofx(self, switch_id: int, pocofx_id: int):
        """
        Start a specific PocoFx on a switch.

        Args:
            switch_id: Switch to control (0-31)
            pocofx_id: PocoFx identifier (0-255)
        """
        data = encode_vsw_pocofx_start(switch_id, pocofx_id)
        self.send_proprietary(data)
        logger.info(f"Started PocoFx {pocofx_id} on switch {switch_id}")
    def pause_pocofx(self, switch_id: int):
        """Pause/resume PocoFx playback."""
        data = encode_vsw_simple_action(switch_id, VSwAction.POCOFX_PAUSE)
        self.send_proprietary(data)
        logger.info(f"Paused/Resumed PocoFx on switch {switch_id}")

    def query_switch_state(self, switch_id: int):
        """
        Query the current state of a switch.
        Device should respond with EXTSW_STATE message.

        Args:
            switch_id: Switch to query (0-31)
        """
        data = encode_vsw_state_query(switch_id)
        self.send_proprietary(data)
        logger.debug(f"Queried state for switch {switch_id}")


class PocoCANMonitor:
    """
    Monitor and decode Poco CAN messages.
    """

    def __init__(self, interface: PocoCANInterfaceBase):
        self.interface = interface
        self.running = False

    def decode_message(self, msg: can.Message):
        """Decode and print a CAN message."""
        # Extract PGN from CAN ID
        pgn = ((msg.arbitration_id >> 8) & 0x3FFFF)
        source = msg.arbitration_id & 0xFF

        print(f"\n[{msg.timestamp:.3f}] PGN {pgn} (0x{pgn:05X}) from 0x{source:02X}")
        print(f"  Data: {msg.data.hex(' ').upper()}")

        # Try to decode known PGNs
        if pgn == PGN_PROPRIETARY_SINGLE_FRAME and len(msg.data) >= 3:
            self._decode_proprietary(msg.data)
        elif pgn == PGN_BINARY_SWITCH_STATUS:
            self._decode_binary_status(msg.data)

    def _decode_proprietary(self, data: bytes):
        """Decode proprietary PGN 61184."""
        manuf = struct.unpack('<H', data[0:2])[0] & 0x7FF
        industry = (struct.unpack('<H', data[0:2])[0] >> 13) & 0x07
        pid = data[2]

        print(f"  Manufacturer: {manuf} {'(Lumitec)' if manuf == 1512 else ''}")
        print(f"  Industry: {industry} {'(Marine)' if industry == 4 else ''}")
        print(f"  PID: {pid}", end='')

        if pid == ProprietaryID.VSW_SIMPLE_ACTIONS:
            print(" (ExtSw Simple Actions)")
            if len(data) >= 5:
                print(f"    Action: {data[3]} Switch: {data[4]}")
        elif pid == ProprietaryID.VSW_STATE:
            print(" (ExtSw State)")
        elif pid == ProprietaryID.VSW_CUSTOM_HSB:
            print(" (ExtSw Custom HSB)")
            if len(data) >= 8:
                print(f"    Switch: {data[4]} H:{data[5]} S:{data[6]} B:{data[7]}")
        elif pid == ProprietaryID.VSW_POCOFX_ID:
            print(" (ExtSw PocoFx Start)")
        else:
            print()

    def _decode_binary_status(self, data: bytes):
        """Decode binary switch bank status and notify callbacks."""
        if len(data) < 1:
            return

        bank = data[0]
        switch_states = []

        # Decode all 28 switch states
        for i in range(28):
            byte_idx = 1 + (i // 4)
            if byte_idx >= len(data):
                switch_states.append(3)  # N/A if data not available
                continue
            bit_offset = (i % 4) * 2
            state = (data[byte_idx] >> bit_offset) & 0x03
            switch_states.append(state)

        # Store in cache
        self.binary_switch_states[bank] = switch_states

        # Notify callbacks
        for callback in self.binary_callbacks:
            try:
                callback(bank, switch_states)
            except Exception as e:
                logger.warning(f"Binary callback error: {e}")

        logger.debug(f"Updated binary switch status for bank {bank}: "
                    f"{sum(1 for s in switch_states[:10] if s == 1)}/10 switches on")

    def start(self):
        """Start monitoring."""
        print("Poco CAN Monitor - Press Ctrl+C to stop")
        print("=" * 60)
        self.running = True
        self.interface.start_listener(lambda msg: self.decode_message(msg) if self.running else None)

    def stop(self):
        """Stop monitoring."""
        self.running = False


if __name__ == "__main__":
    # Example usage
    logging.basicConfig(level=logging.INFO)

    print("Poco CAN Interface - Test Mode")
    print("=" * 50)

    # Example: Send commands (requires actual CAN hardware)
    try:
        print("Poco CAN Interface Examples")
        print("=" * 40)

        # Level 0 example (Output Channel Control)
        with PocoCANInterfaceLevel0(interface='socketcan', channel='can0') as poco:
            print("\nLevel 0 - Output Channel Control:")
            poco.send_pli_t2hsb(channel=1, hue=0, saturation=15, brightness=15)  # Red, full saturation and brightness
            poco.send_pwm_channel(channel=1, duty_cycle=127)  # 50% PWM
            poco.send_binary_channel(channel=2, state=True)   # Binary ON
            print("Level 0 test completed!")

        # Level 1 example (Binary Switch Bank)
        with PocoCANInterfaceLevel1(interface='socketcan', channel='can0') as poco:
            print("\nLevel 1 - Binary Switch Bank:")
            poco.set_switch_bank(bank=0, switches={0: True, 1: False, 2: True})
            print("Level 1 test completed!")

        # Level 2 example (Virtual Switch Actions)
        with PocoCANInterfaceLevel2(interface='socketcan', channel='can0') as poco:
            print("\nLevel 2 - Virtual Switch Commands:")
            poco.turn_on(0)
            poco.set_color_preset(1, 'red', brightness=200)
            poco.dim_up(2)
            print("Level 2 test completed!")

    except Exception as e:
        print(f"Error: {e}")
        print("Note: This requires CAN hardware. See README for setup.")
