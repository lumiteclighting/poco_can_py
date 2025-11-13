#!/usr/bin/env python3
"""
Simple test script to demonstrate device enumeration.

This script connects to the CAN bus, sends an enumeration request,
and displays all responding Poco devices.

Usage:
    python test_discovery.py --interface socketcan --channel vcan0
"""

import sys
import argparse
import time
import logging

# Add parent directory to path
sys.path.insert(0, '..')

from poco_can.poco_can_interface import PocoCANInterfaceBase

def device_discovered_callback(can_address, device_info):
    """Callback function called when a device is discovered."""
    print(f"\n📍 Device found at address 0x{can_address:02X} ({can_address}):")
    print(f"   Device ID:       0x{device_info['device_id']:06X}")
    print(f"   Channels:        {device_info['num_channels']}")
    print(f"   Protocol Ver:    {device_info['protocol_version']}")
    print(f"   Expander Role:   {device_info['expander_role']}")

def main():
    parser = argparse.ArgumentParser(description='Discover Poco devices on CAN bus')
    parser.add_argument('--interface', default='socketcan',
                       help='CAN interface type (default: socketcan)')
    parser.add_argument('--channel', default='vcan0',
                       help='CAN channel (default: vcan0)')
    parser.add_argument('--timeout', type=float, default=2.0,
                       help='Discovery timeout in seconds (default: 2.0)')
    parser.add_argument('--debug', action='store_true',
                       help='Enable debug logging')

    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )

    print("=" * 60)
    print("Poco Device Discovery Test")
    print("=" * 60)
    print(f"Interface: {args.interface}")
    print(f"Channel:   {args.channel}")
    print(f"Timeout:   {args.timeout}s")
    print("=" * 60)

    try:
        # Create interface
        poco = PocoCANInterfaceBase(
            interface=args.interface,
            channel=args.channel,
            source_address=0,
            poco_address=0xFF  # Broadcast
        )

        # Connect to bus
        print("\n🔌 Connecting to CAN bus...")
        poco.connect()
        print("✅ Connected")

        # Register discovery callback
        poco.add_enumeration_callback(device_discovered_callback)

        # Start listener to receive responses
        poco.start_listener()

        # Send enumeration request
        print(f"\n📡 Sending enumeration request (broadcast)...")
        poco.send_enumerate_request()

        # Wait for responses
        print(f"⏱️  Waiting {args.timeout}s for responses...\n")
        time.sleep(args.timeout)

        # Display summary
        devices = poco.get_discovered_devices()
        print("\n" + "=" * 60)
        print(f"Discovery complete! Found {len(devices)} device(s)")
        print("=" * 60)

        if devices:
            print("\nSummary of discovered devices:")
            print("-" * 60)
            for addr, info in sorted(devices.items()):
                print(f"  0x{addr:02X} ({addr:3d}): "
                      f"ID=0x{info['device_id']:06X} "
                      f"Ch={info['num_channels']} "
                      f"Ver={info['protocol_version']} "
                      f"ExpanderRole={info['expander_role']}")
        else:
            print("\n⚠️  No devices responded to enumeration request")
            print("   Check that:")
            print("   - Poco devices are powered and on the CAN bus")
            print("   - CAN bus is properly terminated")
            print("   - CAN interface is correctly configured")

        # Cleanup
        poco.disconnect()
        print("\n✅ Disconnected from CAN bus")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        if args.debug:
            traceback.print_exc()
        return 1

    return 0

if __name__ == "__main__":
    sys.exit(main())
