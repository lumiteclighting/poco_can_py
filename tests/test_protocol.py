#!/usr/bin/env python3
"""
Quick test script to verify Poco CAN protocol encoding.
This tests the protocol encoder without requiring CAN hardware.
"""

from poco_can.poco_can_protocol import *

def test_protocol_encoding():
    """Test all protocol encoding functions."""
    print("="*70)
    print("Poco CAN Protocol Encoder - Verification Test")
    print("="*70)

    all_passed = True

    # Test 1: VSw Simple Action
    print("\n[Test 1] VSw: Simple Action - Turn ON switch 5")
    data = encode_vsw_simple_action(5, VSwAction.ON)
    print(f"  Expected length: 8 bytes")
    print(f"  Actual length: {len(data)} bytes")
    print(f"  Data: {data.hex(' ').upper()}")
    print(f"  Breakdown:")
    print(f"    Bytes 0-2 (Header): {data[0:3].hex(' ').upper()}")
    print(f"    Byte 3 (Action): {data[3]} (ON={VSwAction.ON})")
    print(f"    Byte 4 (Switch): {data[4]}")

    assert len(data) == 8, "Wrong length"
    assert data[3] == VSwAction.ON, "Wrong action"
    assert data[4] == 5, "Wrong switch ID"
    print("  ✅ PASS")

    # Test 2: VSw Custom HSB
    print("\n[Test 2] VSw: Custom HSB - Set switch 2 to Red (H=0, S=255, B=200)")
    data = encode_vsw_hsb(2, HSBAction.T2HSB, 0, 255, 200)
    print(f"  Data: {data.hex(' ').upper()}")
    print(f"  Breakdown:")
    print(f"    Bytes 0-2 (Header): {data[0:3].hex(' ').upper()}")
    print(f"    Byte 3 (Action): {data[3]} (T2HSB={HSBAction.T2HSB})")
    print(f"    Byte 4 (Switch): {data[4]}")
    print(f"    Byte 5 (Hue): {data[5]}")
    print(f"    Byte 6 (Sat): {data[6]}")
    print(f"    Byte 7 (Bright): {data[7]}")

    assert len(data) == 8, "Wrong length"
    assert data[3] == HSBAction.T2HSB, "Wrong action"
    assert data[4] == 2, "Wrong switch ID"
    assert data[5] == 0, "Wrong hue"
    assert data[6] == 255, "Wrong saturation"
    assert data[7] == 200, "Wrong brightness"
    print("  ✅ PASS")

    # Test 3: VSw PocoFx Start
    print("\n[Test 3] VSw: PocoFx Start - Switch 10, PocoFx 7")
    data = encode_vsw_pocofx_start(10, 7)
    print(f"  Data: {data.hex(' ').upper()}")
    print(f"  Breakdown:")
    print(f"    Bytes 0-2 (Header): {data[0:3].hex(' ').upper()}")
    print(f"    Byte 3 (Switch): {data[3]}")
    print(f"    Byte 4 (PocoFx): {data[4]}")

    assert len(data) == 8, "Wrong length"
    assert data[3] == 10, "Wrong switch ID"
    assert data[4] == 7, "Wrong PocoFx ID"
    print("  ✅ PASS")

    # Test 4: VSw PLI Raw Message
    print("\n[Test 4] PLI Raw - Channel 3, Message 0x12345678")
    data = encode_outch_pli_raw(3, 0x12345678)
    print(f"  Data: {data.hex(' ').upper()}")
    print(f"  Breakdown:")
    print(f"    Bytes 0-2 (Header): {data[0:3].hex(' ').upper()}")
    print(f"    Byte 3 (Channel): {data[3]}")
    print(f"    Bytes 4-7 (PLI): 0x{struct.unpack('<I', data[4:8])[0]:08X}")

    assert len(data) == 8, "Wrong length"
    assert data[3] == 3, "Wrong channel"
    assert struct.unpack('<I', data[4:8])[0] == 0x12345678, "Wrong PLI message"
    print("  ✅ PASS")

    # Test 5: CAN ID Calculation
    print("\n[Test 5] CAN ID Calculation for PGN 61184")
    can_id = calculate_pgn_can_id(
        pgn=61184,
        priority=3,
        source_addr=0,
        destination_addr=0xFF
    )
    print(f"  CAN ID: 0x{can_id:08X}")
    print(f"  Priority: {(can_id >> 26) & 0x07}")
    print(f"  PGN: {((can_id >> 8) & 0x3FFFF)}")
    print(f"  Source: {can_id & 0xFF}")

    assert (can_id >> 26) & 0x07 == 3, "Wrong priority"
    assert can_id & 0xFF == 0, "Wrong source address"
    print("  ✅ PASS")

    # Test 6: Binary Switch Control
    print("\n[Test 6] Binary Switch Bank Control - PGN 127502")
    states = [1, 0, 1, 0] + [3] * 24  # On, Off, On, Off, then NoChange for rest
    data = encode_binary_switch_control(bank=1, switch_states=states)
    print(f"  Data: {data.hex(' ').upper()}")
    print(f"  Bank: {data[0]}")
    print(f"  First 4 switches: {states[0:4]}")

    assert len(data) == 8, "Wrong length"
    assert data[0] == 1, "Wrong bank"
    # Verify first 4 switch states (2 bits each in byte 1)
    assert (data[1] & 0x03) == 1, "Switch 0 should be On"
    assert ((data[1] >> 2) & 0x03) == 0, "Switch 1 should be Off"
    assert ((data[1] >> 4) & 0x03) == 1, "Switch 2 should be On"
    assert ((data[1] >> 6) & 0x03) == 0, "Switch 3 should be Off"
    print("  ✅ PASS")

    # Test 7: Convenience Functions
    print("\n[Test 7] Convenience Functions")
    can_id, data = create_vsw_turn_on_message(15)
    print(f"  Turn ON switch 15:")
    print(f"    CAN ID: 0x{can_id:08X}")
    print(f"    Data: {data.hex(' ').upper()}")
    assert data[3] == VSwAction.ON, "Wrong action"
    assert data[4] == 15, "Wrong switch ID"
    print("  ✅ PASS")

    can_id, data = create_vsw_set_color_message(3, 85, 255, 180)
    print(f"  Set color (Green) switch 3:")
    print(f"    CAN ID: 0x{can_id:08X}")
    print(f"    Data: {data.hex(' ').upper()}")
    assert data[4] == 3, "Wrong switch ID"
    assert data[5] == 85, "Wrong hue (should be green)"
    assert data[6] == 255, "Wrong saturation"
    assert data[7] == 180, "Wrong brightness"
    print("  ✅ PASS")

    print("\n" + "="*70)
    print("✅ ALL TESTS PASSED!")
    print("="*70)
    print("\nProtocol encoder is working correctly.")
    print("Ready to use with actual CAN hardware.")
    print("\nNext steps:")
    print("  1. Set up CAN interface (see README.md)")
    print("  2. Run examples.py to test with hardware")
    print("  3. Use poco_can_interface.py in your application")


def test_color_values():
    """Test color HSB value conversions."""
    print("\n" + "="*70)
    print("Color Value Reference")
    print("="*70)

    colors = {
        'Red': 0,
        'Orange': 21,
        'Yellow': 42,
        'Green': 85,
        'Cyan': 127,
        'Blue': 170,
        'Magenta': 212,
    }

    print("\nHue Values (0-255):")
    for name, hue in colors.items():
        print(f"  {name:10s}: {hue:3d} (0x{hue:02X})")

    print("\nSaturation Values (0-255):")
    print(f"  White:     0   (no color)")
    print(f"  Pastel:    64  (25% color)")
    print(f"  Medium:    128 (50% color)")
    print(f"  Vivid:     192 (75% color)")
    print(f"  Full:      255 (100% color)")

    print("\nBrightness Values (0-255):")
    print(f"  Off:       0   (0%)")
    print(f"  Dim:       64  (25%)")
    print(f"  Medium:    128 (50%)")
    print(f"  Bright:    192 (75%)")
    print(f"  Full:      255 (100%)")


if __name__ == "__main__":
    try:
        test_protocol_encoding()
        test_color_values()

        print("\n" + "="*70)
        print("✨ Protocol verification complete!")
        print("="*70)

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
