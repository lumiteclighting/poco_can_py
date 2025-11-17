"""
Poco CAN Bus Protocol Implementation
=====================================

This module provides a Python implementation of the Lumitec Poco proprietary
CAN bus protocol for controlling lighting devices via NMEA2000.

Protocol Levels:
- Level 0: Output Channel Control (PGN 61184 PIDs 6-8,16)
- Level 1: Binary Switch Bank (PGN 127501/127502)
- Level 2: Proprietary VSw Actions (PGN 61184 PIDs 1-4)
- Level 3: Full NMEA2000 Lighting System (PGN 130xxx) [Not implemented here]

This implementation focuses on Levels 0, 1, and 2 commands for simple
remote control without the complexity of full NMEA2000 lighting protocol.

Author: Lumitec LLC
Date: October 2025
License: Reference implementation for third-party integration
"""

import struct
from enum import IntEnum
from typing import Optional, Tuple


# NMEA2000 Constants
NMEA2K_MANUFACTURER_LUMITEC = 1512
NMEA2K_INDUSTRY_MARINE = 4
PGN_PROPRIETARY_SINGLE_FRAME = 61184
PGN_BINARY_SWITCH_STATUS = 127501
PGN_BINARY_SWITCH_CONTROL = 127502

# Fault flag bit definitions for OUTPUTCH_STATUS (PID 32) Mode & Status field
# Bits 0-2 are reserved for channel mode (0=OFF, 1=BIN, 2=PWM, 3=PLI, 4-7=Reserved)
# Bits 3-7 are fault/status flags
FAULT_FLAG_OVERCURRENT = 0x08      # Bit 3: OC: Over-current fault (also SC: Short-circuit)
FAULT_FLAG_UNDERVOLTAGE = 0x10     # Bit 4: UV: Under-voltage fault (dead battery or blown input fuse)
FAULT_FLAG_OVERTEMPERATURE = 0x20  # Bit 5: Reserved (Over-temperature - not available yet)
FAULT_FLAG_PLI_FAULT = 0x40        # Bit 6: Reserved (PLI fault - not available yet)
# Bit 7: Reserved for future use


class VSwAction(IntEnum):
    """Virtual Switch Action IDs for PID 1: Simple Actions
    Valid action IDs range from 0-65 for CAN protocol use.
    """
    NO_ACTION = 0      # Just return state, no change
    OFF = 1            # Turn off (Bright=0)
    ON = 2             # Turn on (default HSB)
    DIM_DOWN = 3       # Brightness -10%
    DIM_UP = 4         # Brightness +10%
    T2BD = 5           # Delta Brightness (requires delta parameter)
    POCOFX_START = 6   # Start/Play PocoFx pattern (requires pattern ID)
    POCOFX_PAUSE = 7   # Pause/Resume PocoFx pattern
    T2HSB = 8          # Transition to default HSB
    T2HS = 9           # Transition to default HS (brightness depends on state)
    T2B = 10           # Transition to default Brightness only
    T2RGB = 11         # Transition to RGB color (requires red, green, blue parameters)
    COLOR_WHITE = 20   # Change color to White
    COLOR_RED = 21     # Change color to Red
    COLOR_GREEN = 22   # Change color to Green
    COLOR_BLUE = 23    # Change color to Blue
    PLAY_PAUSE = 31    # Toggle PocoFx/pattern play/pause
    TOGGLE = 32        # Toggle On/Off and Scene Select advance
    ON_SCENE_1 = 33    # Choose Scene Select child switch 1
    # ON_SCENE_2 through ON_SCENE_33 = 34-65


class ColorType(IntEnum):
    """Color Type values for VSW_STATE (PID 2) Color Type field"""
    NONE = 0        # Unavailable, N/A, or No-Change
    HUE_SAT = 1     # Solid Color in Hue+Saturation space
    CCT = 2         # White CCT Color Temperature in Kelvin (not implemented yet)
    FX_ID = 3       # Program/Effect Active by PocoFx ID
    COMPLEX = 4     # Scene Active - multiple colors simultaneously
    MUTEX = 5       # Scene Select mutex group - value indicates active child
    CUSTOM_PLI = 6  # Raw PLI message sent, meaning unknown to Poco
    RGB = 7         # Solid color in RGB space (reserved, not used in VSW_STATE)


class ProprietaryID(IntEnum):
    """Proprietary ID (PID) values for PGN 61184"""
    VSW_SIMPLE_ACTIONS = 1       # Simple virtual switch action
    VSW_STATE = 2                # Virtual switch state (TX only)
    VSW_CUSTOM_HSB = 3           # Custom HSB, HS, or B action
    VSW_POCOFX_ID = 4            # PocoFx playback action
    VSW_CUSTOM_RGB = 5           # Custom RGB color action
    VSW_DELTABRIGHT = 6          # Delta Brightness (no change to color)

    OUTPUTCH_STATUS = 32         # Transmit channel status (TX only)
    OUTPUTCH_BIN_ONOFF = 33      # Binary on/off for output channel
    OUTPUTCH_PWM_DUTY = 34       # PWM duty cycle control
    OUTPUTCH_PWM_CONFIG = 35     # reserved for future use (frequency, gamma, min-duty, default transition)
    OUTPUTCH_PLI_RAW = 36        # Direct PLI message (32-bit command)
    OUTPUTCH_PLI_CONFIG = 37     # reserved for future use (timing, sync)
    OUTPUTCH_PLI_POWER = 38      # reserved for future use (set power on with start-inhibit and power off)
    OUTPUTCH_STATUS_REQUEST = 39 # Request channel status (responds with OUTPUTCH_STATUS)

    OUTPUTCH_PLI_T2HSB = 40      # PLI Transition to Hue, Sat, Bright
    OUTPUTCH_PLI_T2RGB = 41      # PLI Transition to RGB (single message, not absolute color-space)
    OUTPUTCH_PLI_T2HS = 42       # PLI Transition to new Hue and Sat
    OUTPUTCH_PLI_T2B = 43        # PLI Transition to Brightness (no change in Hue, Unit: 0.39% = 1/255)
    OUTPUTCH_PLI_T2BD = 44       # PLI Transition Brightness by Delta (Unit: +/- 0.79% = 1/127)
    OUTPUTCH_PLI_T2P = 45        # PLI Transition to Pattern (see pattern table)

    ENUMERATE_REQUEST = 128      # Enumerate request for device discovery
    ENUMERATE_RESPONSE = 129     # Enumerate response with device info


class HSBAction(IntEnum):
    """Action IDs for PID 3: Custom HSB"""
    T2HSB = 8   # Set custom Hue, Saturation, Brightness
    T2HS = 9    # Set custom Hue, Saturation (brightness depends on state)
    T2B = 10    # Set custom Brightness only


def encode_proprietary_header(manufacturer_code: int,
                              industry_code: int,
                              proprietary_id: int) -> bytes:
    """
    Encode the 3-byte proprietary PGN header.

    Args:
        manufacturer_code: 11-bit manufacturer code (0-2047)
        industry_code: 3-bit industry code (0-7)
        proprietary_id: 8-bit proprietary ID (0-255)

    Returns:
        3 bytes: [manufacturer_lo+reserved, manufacturer_hi+industry, proprietary_id]
    """
    # Byte 0-1: Manufacturer code (11 bits) + Reserved (2 bits) + Industry (3 bits)
    proprietary_info = (manufacturer_code & 0x7FF) | (0b11 << 11) | ((industry_code & 0x07) << 13)
    header = struct.pack('<HB', proprietary_info, proprietary_id)
    return header

def _pack_vsw_common(prop_id, act_id, sw_id, byte5, byte6, byte7):
    header = encode_proprietary_header(
        NMEA2K_MANUFACTURER_LUMITEC,
        NMEA2K_INDUSTRY_MARINE,
        prop_id
    )
    return header + struct.pack('BBBBB', act_id, sw_id, byte5, byte6, byte7)

def encode_vsw_simple_action(switch_id: int, action_id: VSwAction) -> bytes:
    """
    Encode PID 1: Virtual Switch Simple Actions

    PGN 61184, PID 1 - Single frame (8 bytes)
    Field layout:
    - Bytes 0-2: Proprietary header (Manufacturer, Industry, PID)
    - Byte 3: Action ID
    - Byte 4: Switch ID (0-31)
    - Bytes 5-7: Unused/Reserved

    Args:
        switch_id: Virtual Switch ID (0-31)
        action_id: Action to perform (see ExtSwAction enum)

    Returns:
        8 bytes ready to send as CAN data
    """

    return _pack_vsw_common(ProprietaryID.VSW_SIMPLE_ACTIONS, action_id, switch_id, 0xFF, 0xFF, 0xFF)


def encode_vsw_hsb(switch_id: int,
                           action: HSBAction,
                           hue: int,
                           saturation: int,
                           brightness: int) -> bytes:
    """
    Encode PID 3: Virtual Switch Custom HSB

    PGN 61184, PID 3 - Single frame (8 bytes)
    Field layout:
    - Bytes 0-2: Proprietary header
    - Byte 3: Action ID (8=T2HSB, 9=T2HS, 10=T2B)
    - Byte 4: Switch ID
    - Byte 5: Hue (0-255: 0=Red, 85=Green, 170=Blue, 255≈Red)
    - Byte 6: Saturation (0-255: 0=White, 255=Fully saturated)
    - Byte 7: Brightness (0-255: 0=Off, 255=Full)

    Args:
        switch_id: Virtual Switch ID (0-31)
        action: Which HSB action (T2HSB, T2HS, T2B)
        hue: Color hue (0-255)
        saturation: Color saturation (0-255)
        brightness: Brightness level (0-255)

    Returns:
        8 bytes ready to send as CAN data
    """

    return _pack_vsw_common(ProprietaryID.VSW_CUSTOM_HSB, action, (switch_id & 0xFF), (hue & 0xFF), (saturation & 0xFF), (brightness & 0xFF))


def encode_vsw_custom_rgb(switch_id: int, red: int, green: int, blue: int) -> bytes:
    """
    Encode PID 5: Virtual Switch Custom RGB Color

    PGN 61184, PID 5 - Single frame (8 bytes)
    Field layout:
    - Bytes 0-2: Proprietary header
    - Byte 3: Action ID (11 = T2RGB)
    - Byte 4: Switch ID (0-31)
    - Byte 5: Red (0-255)
    - Byte 6: Green (0-255)
    - Byte 7: Blue (0-255)

    Args:
        switch_id: Virtual Switch ID (0-31)
        red: Red component (0-255)
        green: Green component (0-255)
        blue: Blue component (0-255)

    Returns:
        8 bytes ready to send as CAN data
    """

    return _pack_vsw_common(ProprietaryID.VSW_CUSTOM_RGB, VSwAction.T2RGB, (switch_id & 0xFF), (red & 0xFF), (green & 0xFF), (blue & 0xFF))

def encode_vsw_delta_brightness(switch_id: int, delta: int) -> bytes:
    """
    Encode PID 6: Virtual Switch Delta Brightness (T2BD)

    PGN 61184, PID 6 - Single frame (8 bytes)
    Field layout:
    - Bytes 0-2: Proprietary header
    - Byte 3: Action ID (5=T2BD)
    - Byte 4: Switch ID (0-31)
    - Byte 5: Delta Brightness (-128 to +127)
    - Bytes 6-7: Unused/Reserved

    Args:
        switch_id: Virtual Switch ID (0-31)
        delta: Brightness delta (-128 to +127)

    Returns:
        8 bytes ready to send as CAN data
    """

    # Clamp delta to valid range
    delta = max(-128, min(127, delta))

    return _pack_vsw_common(ProprietaryID.VSW_DELTABRIGHT, VSwAction.T2BD, (switch_id & 0xFF), delta, 0xFF, 0xFF)


def encode_vsw_pocofx_start(switch_id: int, pocofx_id: int) -> bytes:
    """
    Encode PID 4: Virtual Switch Start PocoFx by ID

    PGN 61184, PID 4 - Single frame (8 bytes)
    Field layout:
    - Bytes 0-2: Proprietary header
    - Byte 3: Action ID - POCOFX_START
    - Byte 4: Switch ID (0-253)
    - Byte 5: PocoFx ID (0-255)
    - Bytes 6-7: Unused/Reserved

    Args:
        switch_id: Virtual Switch ID (0-31)
        PocoFx_id: PocoFx identifier (0-255)

    Returns:
        8 bytes ready to send as CAN data
    """

    return _pack_vsw_common(ProprietaryID.VSW_POCOFX_ID, VSwAction.POCOFX_START, (switch_id & 0xFD), (pocofx_id & 0xFF), 0xFF, 0xFF)


def encode_outch_binary_channel(channel: int, state: int) -> bytes:
    """
    Encode PID 33: Output Channel Binary Control

    PGN 61184, PID 33 - Single frame (8 bytes)
    Field layout:
    - Bytes 0-2: Proprietary header
    - Byte 3: Channel number (1-4)
    - Byte 4: State (0=Off, 1=On)
    - Bytes 5-7: Unused/Reserved

    Args:
        channel: Poco output channel (1-4)
        state: 0=Off, 1=On

    Returns:
        8 bytes ready to send as CAN data
    """
    header = encode_proprietary_header(
        NMEA2K_MANUFACTURER_LUMITEC,
        NMEA2K_INDUSTRY_MARINE,
        ProprietaryID.OUTPUTCH_BIN_ONOFF
    )

    payload = struct.pack('BB', channel, state)
    padding = b'\xFF\xFF\xFF'  # Unused bytes

    return header + payload + padding


def encode_outch_pwm_channel(channel: int, duty_cycle: int) -> bytes:
    """
    Encode PID 34: Output Channel PWM Control

    PGN 61184, PID 34 - Single frame (8 bytes)
    Field layout:
    - Bytes 0-2: Proprietary header
    - Byte 3: Channel number (1-4)
    - Byte 4: Duty cycle percentage (0-100)
    - Bytes 5-7: Unused/Reserved

    Args:
        channel: Poco output channel (1-4)
        duty_cycle: PWM duty cycle 0-100%

    Returns:
        8 bytes ready to send as CAN data
    """
    header = encode_proprietary_header(
        NMEA2K_MANUFACTURER_LUMITEC,
        NMEA2K_INDUSTRY_MARINE,
        ProprietaryID.OUTPUTCH_PWM_DUTY
    )

    payload = struct.pack('BB', channel, duty_cycle)
    padding = b'\xFF\xFF\xFF'  # Unused bytes

    return header + payload + padding


def encode_outch_pli_raw(channel: int, pli_message: int) -> bytes:
    """
    Encode PID 36: Output Channel PLI Raw Message

    PGN 61184, PID 36 - Single frame (8 bytes)
    Field layout:
    - Bytes 0-2: Proprietary header
    - Byte 3: Channel number (1-4)
    - Bytes 4-7: 32-bit PLI message

    Args:
        channel: Poco output channel (1-4)
        pli_message: 32-bit PLI command

    Returns:
        8 bytes ready to send as CAN data
    """
    header = encode_proprietary_header(
        NMEA2K_MANUFACTURER_LUMITEC,
        NMEA2K_INDUSTRY_MARINE,
        ProprietaryID.OUTPUTCH_PLI_RAW
    )

    payload = struct.pack('<BI', channel, pli_message)

    return header + payload

def _pack_pli_common(prop_id, chan, clan, trans, byte6, byte7):
    #common validate for chan, clan, transition
    chan = max(0, min(4, chan))
    clan = max(0, min(63, clan))  # 0-63
    trans = max(0, min(7, trans))  # 0-7

    header = encode_proprietary_header(
        NMEA2K_MANUFACTURER_LUMITEC,
        NMEA2K_INDUSTRY_MARINE,
        prop_id
    )
    byte4_clan = (clan & 0x3F)
    byte5_trans = (trans & 0x07)
    return header + struct.pack('BBBBB', chan, byte4_clan, byte5_trans, byte6, byte7)

def encode_outch_pli_t2hsb(channel: int, hue: int, saturation: int, brightness: int,
                          pli_clan: int = 0, transition: int = 0) -> bytes:
    """
    Encode PID 40: Output Channel PLI T2HSB

    PGN 61184, PID 40 - Single frame (8 bytes)
    Convenience command to send PLI T2HSB message to a specific channel.

    Field layout per protocol spec:
    - Bytes 0-1: Manufacturer Code (11 bits) + Reserved (2 bits) + Industry Code (3 bits)
    - Byte 2: Proprietary ID (40)
    - Byte 3: Channel (1-4, 0: All Chs)
    - Byte 4: PLI Clan (0-63)
    - Byte 5: Transition (0-7)
    - Byte 6: Hue (8 bits, 0-255)
    - Byte 7: Saturation (3 bits: 0-7, bits 0-2) + Brightness (4 bits: 0-15, bits 3-6)

    Args:
        channel: Poco output channel (1-4)
        hue: Color hue (0-255: 0=Red, 85=Green, 170=Blue, 255=close to Red)
        saturation: Color saturation (0-7: 0=White, 7=Fully saturated)
        brightness: Brightness level (0-15: 0=Off, 15=Full bright)
        pli_clan: PLI Address/Clan (0-63: 0=All, 1-63=see table)
        transition: Transition Time ID (0-7: see table)

    Returns:
        8 bytes ready to send as CAN data
    """

    # Validate ranges according to protocol spec
    hue = max(0, min(255, hue))
    saturation = max(0, min(15, saturation))  # 4 bits = 0-15
    brightness = max(0, min(15, brightness))  # 4 bits = 0-15

    # Byte 6: Hue (full 8 bits)
    byte6 = hue
    # Byte 7: Saturation (4 bits, bits 0-3) + Brightness (4 bits, bits 4-7)
    byte7 = (saturation & 0x0F) | ((brightness & 0x0F) << 4)

    return _pack_pli_common(ProprietaryID.OUTPUTCH_PLI_T2HSB, channel, pli_clan, transition, byte6, byte7)


def encode_outch_pli_t2rgb(channel: int, red: int, green: int, blue: int,
                           pli_clan: int = 0, transition: int = 0) -> bytes:
    """
    Encode PID 41: Output Channel PLI T2RGB

    PGN 61184, PID 41 - Single frame (8 bytes)
    Command to send PLI T2RGB (5-bit RGB) message to a specific channel.

    Field layout per firmware implementation:
    - Bytes 0-2: Proprietary header (Lumitec mfr, industry, PID)
    - Byte 3: Channel (1-4)
    - Byte 4: PLI Clan (0-63)
    - Byte 5: Transition (0-7)
    - Byte 6: Red (5 bits, bits 0-4) + Transition MSB (bit 7)
    - Byte 6: Green (5 bits, bits 0-4)
    - Byte 7: Blue (5 bits, bits 0-4) & 1 bit reserved (bit 7)

    Args:
        channel: Poco output channel (1-4)
        red: Red intensity (0-31: 5-bit value)
        green: Green intensity (0-31: 5-bit value)
        blue: Blue intensity (0-31: 5-bit value)
        pli_clan: PLI Address/Clan (0-63: 0=All, 1-63=see table)
        transition: Transition Time ID (0-7: see table)

    Returns:
        8 bytes ready to send as CAN data
    """

    # Validate ranges
    red = max(0, min(31, red))      # 5 bits = 0-31
    green = max(0, min(31, green))  # 5 bits = 0-31
    blue = max(0, min(31, blue))    # 5 bits = 0-31

    rgb_packed = (red & 0x1F) | ((green & 0x1F) << 5) | ((blue & 0x1F) << 10)

    # Byte 6:  Lower 8 bit segment of rgb packed bytes
    byte6 = rgb_packed & 0xFF
    # Byte 7: Upper 8 bit  segment of rgb packed bytes
    byte7 = (rgb_packed >> 8) & 0xFF

    return _pack_pli_common(ProprietaryID.OUTPUTCH_PLI_T2RGB, channel, pli_clan, transition, byte6, byte7)

def encode_outch_pli_t2hs(channel: int, hue: int, saturation: int,
                          pli_clan: int = 0, transition: int = 0) -> bytes:
    """
    Encode PID 42: Output Channel PLI T2HS

    PGN 61184, PID 42 - Single frame (8 bytes)
    Command to send PLI T2HS (Hue/Saturation only) message to a specific channel.

    Field layout per firmware implementation:
    - Bytes 0-2: Proprietary header (Lumitec mfr, industry, PID)
    - Byte 3: Channel (1-4)
    - Byte 4: PLI Clan (0-63)
    - Byte 5: Transition (0-7)
    - Byte 6: Hue (full 8 bits)
    - Byte 7: Saturation (4 bits, bits 0-3) +  Reserved (0xFF bits 4-7)

    Args:
        channel: Poco output channel (1-4)
        hue: Color hue (0-255: 0=Red, 85=Green, 170=Blue, 255=close to Red)
        saturation: Color saturation (0-255: 0=White, 255=Fully saturated)
                   NOTE: Will be scaled to 4-bit (0-15) for transmission
        pli_clan: PLI Address/Clan (0-63: 0=All, 1-63=see table)
        transition: Transition Time ID (0-7: see table)

    Returns:
        8 bytes ready to send as CAN data
    """

    # Validate ranges
    hue = max(0, min(255, hue))
    saturation = max(0, min(15, saturation))

    # Byte 6: Hue (full 8 bits)
    byte6 = hue & 0xFF
    # Byte 7: Saturation (4 bits, bits 0-3) & Reserved- 0xF (bits 4-7)
    byte7 = (saturation & 0x0F) | (0xF << 4)

    return _pack_pli_common(ProprietaryID.OUTPUTCH_PLI_T2HS, channel, pli_clan, transition, byte6, byte7)


def encode_outch_pli_t2b(channel: int, brightness: int,
                         pli_clan: int = 0, transition: int = 0) -> bytes:
    """
    Encode PID 43: Output Channel PLI T2B

    PGN 61184, PID 43 - Single frame (8 bytes)
    Command to send PLI T2B (Brightness only) message to a specific channel.

    Field layout per firmware implementation:
    - Bytes 0-2: Proprietary header (Lumitec mfr, industry, PID)
    - Byte 3: Channel (1-4)
    - Byte 4: PLI Clan (0-63)
    - Byte 5: Transition (0-7)
    - Byte 6: Brightness (full 8 bits, 0-255)
    - Byte 7: Reserved - 0xFF

    Args:
        channel: Poco output channel (1-4)
        brightness: Brightness level (0-255: 0=Off, 255=Full bright)
        pli_clan: PLI Address/Clan (0-63: 0=All, 1-63=see table)
        transition: Transition Time ID (0-7: see table)

    Returns:
        8 bytes ready to send as CAN data
    """

    # Validate ranges
    brightness = max(0, min(255, brightness))

    # Byte 6: Brightness (full 8 bits)
    byte6 = brightness & 0xFF
    # Byte 7: Reserved
    byte7 = 0xFF

    return _pack_pli_common(ProprietaryID.OUTPUTCH_PLI_T2B, channel, pli_clan, transition, byte6, byte7)


def encode_outch_pli_t2bd(channel: int, delta: int,
                          pli_clan: int = 0, transition: int = 0) -> bytes:
    """
    Encode PID 44: Output Channel PLI T2BD

    PGN 61184, PID 44 - Single frame (8 bytes)
    Command to send PLI T2BD (Brightness Delta) message to a specific channel.

    Field layout per firmware implementation:
    - Bytes 0-2: Proprietary header (Lumitec mfr, industry, PID)
    - Byte 3: Channel (1-4)
    - Byte 4: PLI Clan (0-63)
    - Byte 5: Transition (0-7)
    - Byte 6: Delta Brightness (signed 8 bits, -127 to +127)
    - Byte 7: Reserved - 0xFF

    Args:
        channel: Poco output channel (1-4)
        delta: Brightness delta (-127 to +127: negative=dimmer, positive=brighter)
        pli_clan: PLI Address/Clan (0-63: 0=All, 1-63=see table)
        transition: Transition Time ID (0-7: see table)

    Returns:
        8 bytes ready to send as CAN data
    """

    # Validate ranges
    delta = max(-127, min(127, delta))
    # Convert signed delta to unsigned byte for transmission
    delta_byte = delta & 0xFF if delta >= 0 else (256 + delta)

    # Byte 6: Delta (signed 8 bits as unsigned byte)
    byte6 = delta_byte & 0xFF
    # Byte 7: Reserved
    byte7 = 0xFF

    return _pack_pli_common(ProprietaryID.OUTPUTCH_PLI_T2BD, channel, pli_clan, transition, byte6, byte7)


def encode_outch_pli_t2p(channel: int, pattern: int,
                         pli_clan: int = 0, transition: int = 0) -> bytes:
    """
    Encode PID 45: Output Channel PLI T2P

    PGN 61184, PID 45 - Single frame (8 bytes)
    Command to send PLI T2P (Pattern) message to a specific channel.

    Field layout per firmware implementation:
    - Bytes 0-2: Proprietary header (Lumitec mfr, industry, PID)
    - Byte 3: Channel (1-4)
    - Byte 4: PLI Clan (0-63)
    - Byte 5: Transition (0-7)
    - Byte 6: Pattern ID (full 8 bits, 0-253)
    - Byte 7: Reserved

    Args:
        channel: Poco output channel (1-4)
        pattern: Pattern ID (0-255: see pattern table)
        pli_clan: PLI Address/Clan (0-63: 0=All, 1-63=see table)
        transition: Transition Time ID (0-7: see table)

    Returns:
        8 bytes ready to send as CAN data
    """

    # Validate ranges
    pattern = max(0, min(253, pattern))

    # Byte 5: Pattern ID (full 8 bits)
    byte6 = pattern & 0xFD # 253
    # Byte 7: Reserved
    byte7 = 0xFF

    return _pack_pli_common(ProprietaryID.OUTPUTCH_PLI_T2P, channel, pli_clan, transition, byte6, byte7)


def encode_outch_status_request(channel: int) -> bytes:
    """
    Encode PID 39: Output Channel Status Request

    PGN 61184, PID 39 - Single frame (8 bytes)
    Request current status of one or more output channels.
    Device responds with OUTPUTCH_STATUS (PID 32) message(s).

    Field layout:
    - Bytes 0-2: Proprietary header (Lumitec mfr, industry, PID)
    - Byte 3: Channel (1-4, 0=all channels)
    - Bytes 4-7: Reserved/padding

    Args:
        channel: Output channel to query (1-4), or 0 for all channels

    Returns:
        8 bytes ready to send as CAN data
    """
    header = encode_proprietary_header(
        NMEA2K_MANUFACTURER_LUMITEC,
        NMEA2K_INDUSTRY_MARINE,
        ProprietaryID.OUTPUTCH_STATUS_REQUEST
    )

    # Validate range (0=all, 1-4=specific channel)
    channel = max(0, min(4, channel))

    # Bytes 4-7: Reserved
    return header + struct.pack('BBBBB', channel, 0, 0, 0, 0)


def encode_binary_switch_control(bank: int, switch_states: list) -> bytes:
    """
    Encode PGN 127502: Binary Switch Bank Control

    Single frame (8 bytes) controls up to 28 switches in a bank.
    Each switch uses 2 bits: 0=Off, 1=On, 3=No Change

    Args:
        bank: Bank/Instance number (configurable in Poco, default=1)
        switch_states: List of up to 28 values (0=Off, 1=On, 3=NoChange)

    Returns:
        8 bytes ready to send as CAN data
    """
    data = bytearray(8)
    data[0] = bank & 0xFF

    # Pack 28 switches (2 bits each) into 7 bytes
    for i in range(min(28, len(switch_states))):
        byte_idx = 1 + (i // 4)  # 4 switches per byte
        bit_offset = (i % 4) * 2
        state = switch_states[i] & 0x03
        data[byte_idx] |= (state << bit_offset)

    return bytes(data)


class SwitchState:
    """Represents the complete state of a Poco switch."""
    def __init__(self):
        self.switch_id: int = 0
        self.is_on: bool = False
        self.color_type: int = ColorType.NONE  # ColorType enum value
        self.color_data_0: int = 0  # Meaning depends on color_type
        self.color_data_1: int = 0  # Meaning depends on color_type
        self.brightness: int = 255  # 0-255, 0xFF = N/A
        self.last_updated: float = 0  # timestamp

        # Convenience properties (extracted from color_data based on color_type)
        self.hue: int = 0  # Valid when color_type == HUE_SAT
        self.saturation: int = 255  # Valid when color_type == HUE_SAT
        self.pocofx_id: int = 0  # Valid when color_type == FX_ID
        self.cct_kelvin: int = 0  # Valid when color_type == CCT
        self.mutex_index: int = 0  # Valid when color_type == MUTEX


def encode_vsw_state_query(switch_id: int) -> bytes:
    """
    Encode a state query message (PID 1 with NO_ACTION).
    This requests the device to respond with current switch state.

    Args:
        switch_id: Switch to query (0-31)

    Returns:
        8 bytes ready to send as CAN data
    """
    return encode_vsw_simple_action(switch_id, VSwAction.NO_ACTION)


def decode_vsw_state_response(data: bytes) -> Optional[SwitchState]:
    """
    Decode PID 2: VSW_STATE (switch state broadcast) from Poco device.

    Poco devices automatically broadcast this message when virtual switch state changes.
    This enables third-party devices, multi-Poco systems, and monitoring tools to
    track switch states in real-time.

    Expected format (8 bytes):
    - Bytes 0-2: Proprietary header
    - Byte 3: Switch ID (0-31)
    - Byte 4: Status flags (lower nibble) + Color Type (upper nibble)
    - Byte 5: Color Data 0 (meaning depends on Color Type)
    - Byte 6: Color Data 1 (meaning depends on Color Type)
    - Byte 7: Brightness (0-255, 0xFF = N/A)

    Args:
        data: 8 bytes of CAN message data

    Returns:
        SwitchState object or None if invalid
    """
    if len(data) < 8:
        return None

    # Verify it's a Lumitec proprietary message
    proprietary_info = struct.unpack('<H', data[0:2])[0]
    manufacturer = proprietary_info & 0x7FF
    industry = (proprietary_info >> 13) & 0x07
    pid = data[2]

    if (manufacturer != NMEA2K_MANUFACTURER_LUMITEC or
        industry != NMEA2K_INDUSTRY_MARINE or
        pid != ProprietaryID.VSW_STATE):
        return None

    # Parse state data
    state = SwitchState()
    state.switch_id = data[3]

    # Byte 4: Status flags (lower nibble) + Color Type (upper nibble)
    status_and_type = data[4]
    status_flags = status_and_type & 0x0F
    color_type = (status_and_type >> 4) & 0x0F

    state.is_on = bool(status_flags & 0x01)
    state.color_type = color_type
    state.color_data_0 = data[5]
    state.color_data_1 = data[6]
    state.brightness = data[7]

    # Extract convenience properties based on color type
    if color_type == ColorType.HUE_SAT:
        state.hue = state.color_data_0
        state.saturation = state.color_data_1
    elif color_type == ColorType.FX_ID:
        state.pocofx_id = state.color_data_0
    elif color_type == ColorType.CCT:
        state.cct_kelvin = (state.color_data_1 << 8) | state.color_data_0
    elif color_type == ColorType.MUTEX:
        state.mutex_index = state.color_data_0

    import time
    state.last_updated = time.time()

    return state


def calculate_pgn_can_id(pgn: int,
                                priority: int,
                                source_addr: int,
                                destination_addr: int = 0xFF) -> int:
    """
    Calculate CAN arbitration ID from PGN.

    For single-frame addressable messages (like PGN 61184):
    CAN ID = Priority(3) | Reserved(1) | DP(1) | PF(8) | PS(8) | SA(8)

    Args:
        pgn: Parameter Group Number
        priority: Message priority (0-7, lower=higher priority)
        source_addr: Source address (0-253)
        destination_addr: Destination address (0xFF=broadcast, 0-253=specific)

    Returns:
        29-bit CAN arbitration ID
    """
    # Extract PGN components
    pdu_format = (pgn >> 8) & 0xFF
    pdu_specific = pgn & 0xFF
    data_page = (pgn >> 16) & 0x01

    # For PDU1 format (PF < 240), PS is destination
    # For PDU2 format (PF >= 240), PS is group extension
    if pdu_format < 240:
        # PDU1 - Addressable
        ps = destination_addr
    else:
        # PDU2 - Broadcast
        ps = pdu_specific

    # Build 29-bit CAN ID
    can_id = (priority & 0x07) << 26
    can_id |= (data_page & 0x01) << 24
    can_id |= (pdu_format & 0xFF) << 16
    can_id |= (ps & 0xFF) << 8
    can_id |= (source_addr & 0xFF)

    # Set extended frame bit for python-can
    can_id |= 0x80000000

    return can_id


# Convenience functions for common operations

def create_vsw_turn_on_message(switch_id: int,
                           source_addr: int = 0,
                           destination_addr: int = 0xFF,
                           priority: int = 3) -> Tuple[int, bytes]:
    """
    Create a message to turn on a switch.

    Returns:
        (can_id, data) tuple ready to send
    """
    can_id = calculate_pgn_can_id(
        PGN_PROPRIETARY_SINGLE_FRAME, priority, source_addr, destination_addr
    )
    data = encode_vsw_simple_action(switch_id, VSwAction.ON)
    return (can_id, data)


def create_vsw_turn_off_message(switch_id: int,
                            source_addr: int = 0,
                            destination_addr: int = 0xFF,
                            priority: int = 3) -> Tuple[int, bytes]:
    """Create a message to turn off a switch."""
    can_id = calculate_pgn_can_id(
        PGN_PROPRIETARY_SINGLE_FRAME, priority, source_addr, destination_addr
    )
    data = encode_vsw_simple_action(switch_id, VSwAction.OFF)
    return (can_id, data)


def create_vsw_set_color_message(switch_id: int,
                             hue: int,
                             saturation: int,
                             brightness: int,
                             source_addr: int = 0,
                             destination_addr: int = 0xFF,
                             priority: int = 3) -> Tuple[int, bytes]:
    """
    Create a message to set switch color and brightness.

    Args:
        switch_id: Switch to control (0-31)
        hue: 0-255 (0=Red, 85=Green, 170=Blue)
        saturation: 0-255 (0=White, 255=Full color)
        brightness: 0-255 (0=Off, 255=Full)
    """
    can_id = calculate_pgn_can_id(
        PGN_PROPRIETARY_SINGLE_FRAME, priority, source_addr, destination_addr
    )
    data = encode_vsw_hsb(
        switch_id, HSBAction.T2HSB, hue, saturation, brightness
    )
    return (can_id, data)


def create_vsw_dim_message(switch_id: int,
                      dim_up: bool = True,
                      source_addr: int = 0,
                      destination_addr: int = 0xFF,
                      priority: int = 3) -> Tuple[int, bytes]:
    """Create a message to dim up or down."""
    can_id = calculate_pgn_can_id(
        PGN_PROPRIETARY_SINGLE_FRAME, priority, source_addr, destination_addr
    )
    action = VSwAction.DIM_UP if dim_up else VSwAction.DIM_DOWN
    data = encode_vsw_simple_action(switch_id, action)
    return (can_id, data)


def decode_outch_status(data: bytes) -> dict:
    """
    Decode PID 32: Output Channel Status message.

    PGN 61184, PID 32 - Single frame (8 bytes)
    Field layout:
    - Bytes 0-2: Proprietary header
    - Byte 3: Channel number (1-4)
    - Byte 4: Mode & Status (bits 0-1: mode, bits 2-7: fault flags)
    - Byte 5: Channel Output Level (0-255)
    - Byte 6: Channel Input Voltage (200mV units)
    - Byte 7: Channel Current (100mA units)

    Args:
        data: 8-byte CAN data

    Returns:
        dict with channel, mode, output_level, input_voltage_mv, current_ma, fault_flags
    """
    if len(data) < 8:
        raise ValueError("Invalid data length for PID 32")

    # Skip proprietary header (bytes 0-2)
    channel = data[3]
    mode_and_status = data[4]

    # Extract mode (bits 0-2) and fault flags (bits 3-7)
    mode = mode_and_status & 0x07
    fault_flags = mode_and_status & 0xF8

    output_level = data[5]
    voltage_units = data[6]  # 200mV units
    current_units = data[7]  # 100mA units

    # Convert units
    input_voltage_mv = voltage_units * 200
    current_ma = current_units * 100

    return {
        'channel': channel,
        'mode': mode,
        'output_level': output_level,
        'input_voltage_mv': input_voltage_mv,
        'current_ma': current_ma,
        'fault_flags': fault_flags
    }


def decode_fault_flags(fault_flags: int) -> dict:
    """
    Decode fault flags from OUTPUTCH_STATUS into individual boolean flags.

    Args:
        fault_flags: 8-bit fault flags value (bits 3-7)

    Returns:
        dict with boolean flags for each fault condition
    """
    return {
        'overcurrent': bool(fault_flags & FAULT_FLAG_OVERCURRENT),
        'undervoltage': bool(fault_flags & FAULT_FLAG_UNDERVOLTAGE),
        'overtemperature': bool(fault_flags & FAULT_FLAG_OVERTEMPERATURE),
        'pli_fault': bool(fault_flags & FAULT_FLAG_PLI_FAULT),
    }


def encode_enumerate_request() -> bytes:
    """
    Encode PID 128: Enumerate Request for device discovery.

    PGN 61184, PID 128 - Single frame (8 bytes)
    Field layout:
    - Bytes 0-2: Proprietary header
    - Byte 3: Request flags (0 = full device info)
    - Bytes 4-7: Unused/Reserved (0xFF)

    Returns:
        8 bytes ready to send as CAN data
    """
    header = encode_proprietary_header(
        NMEA2K_MANUFACTURER_LUMITEC,
        NMEA2K_INDUSTRY_MARINE,
        ProprietaryID.ENUMERATE_REQUEST
    )

    payload = struct.pack('B', 0)  # Request flags
    padding = b'\xFF\xFF\xFF\xFF'  # Unused bytes

    return header + payload + padding


def decode_enumerate_response(data: bytes) -> Optional[dict]:
    """
    Decode PID 129: Enumerate Response with device info.

    PGN 61184, PID 129 - Single frame (8 bytes)
    Field layout:
    - Bytes 0-2: Proprietary header
    - Bytes 3-5: Device ID (24-bit, little-endian)
    - Byte 6: Protocol version (lower 4 bits) | Number of channels (upper 4 bits)
    - Byte 7: Capabilities byte
      - bit 0: expander role setting
      - bits 1-7: reserved

    Args:
        data: 8-byte CAN data

    Returns:
        dict with device_id, num_channels, protocol_version, expander_role, or None if invalid
    """
    if len(data) < 8:
        return None

    # Skip proprietary header (bytes 0-2)
    # Bytes 3-5: Device ID (24-bit, little-endian)
    device_id = data[3] | (data[4] << 8) | (data[5] << 16)

    # Byte 6: Protocol version (lower 4 bits) | Number of channels (upper 4 bits)
    byte6 = data[6]
    protocol_version = byte6 & 0x0F
    num_channels = (byte6 >> 4) & 0x0F

    # Byte 7: Capabilities
    capabilities = data[7]
    expander_role = (capabilities & 0x01) != 0

    return {
        'device_id': device_id,
        'num_channels': num_channels,
        'protocol_version': protocol_version,
        'expander_role': expander_role
    }
def create_enumerate_request_message(src_addr: int = 0, dest_addr: int = 0xFF) -> Tuple[int, bytes]:
    """
    Create a complete CAN message for device enumeration request.

    Args:
        src_addr: Source CAN address (0-253, typically 0 for unaddressed master)
        dest_addr: Destination address (0xFF for broadcast)

    Returns:
        Tuple of (CAN ID, 8-byte data)
    """
    can_id = calculate_pgn_can_id(PGN_PROPRIETARY_SINGLE_FRAME, 6, src_addr, dest_addr)
    data = encode_enumerate_request()
    return (can_id, data)


if __name__ == "__main__":
    # Self-test: Print example messages
    print("Poco Protocol Encoder - Self Test")
    print("=" * 50)

    print("\n1. Turn ON switch 0:")
    can_id, data = create_vsw_turn_on_message(0)
    print(f"   CAN ID: 0x{can_id:08X}")
    print(f"   Data: {data.hex(' ')}")

    print("\n2. Set switch 1 to Red (Hue=0, Sat=255, Bright=200):")
    can_id, data = create_vsw_set_color_message(1, 0, 255, 200)
    print(f"   CAN ID: 0x{can_id:08X}")
    print(f"   Data: {data.hex(' ')}")

    print("\n3. Dim up switch 2:")
    can_id, data = create_vsw_dim_message(2, dim_up=True)
    print(f"   CAN ID: 0x{can_id:08X}")
    print(f"   Data: {data.hex(' ')}")

    print("\n4. Start PocoFx 5 on switch 3:")
    can_id = calculate_pgn_can_id(PGN_PROPRIETARY_SINGLE_FRAME, 3, 0, 0xFF)
    data = encode_vsw_pocofx_start(3, 5)
    print(f"   CAN ID: 0x{can_id:08X}")
    print(f"   Data: {data.hex(' ')}")
