# Poco CAN Python Examples

Python-based control library and examples for the Lumitec Poco CAN bus proprietary protocol. This provides a cross-platform reference implementation for third-party integration and testing.

## Quick Start

### 1. Example GUI Launcher

This script should install the necessary requirements into a python virtual environment and run a launcher GUI to demonstrate the examples. 
```bash
./start_example.sh
```

## Installation

### Prerequisites

1. **OS**: 
   - Linux (tested with Ubuntu 24.04)
   - Windows (not tested)
   - MacOS (not tested)
   
2. **Python 3.7+** (tested with Python 3.8+)

3. **CAN Hardware and Driver**
   - Any CAN hardware and driver supported by **python-can**. See list: 
   https://python-can.readthedocs.io/en/stable/interfaces.html
   - We recommend **SocketCAN** on Linux. (tested with PEAK PCAN-USB)


### Linux + SocketCAN Setup

1. **Find the CAN interface:**
   ```bash
   # Show kernel messages. (Ctrl-C to quit)
   sudo dmesg -w
   ```
   Now plug-in the CAN adapter and look for a new line to appear like this: 
   ```
   [...] peak_usb 1-2.3:1.0 can0: attached to PCAN-USB channel 0 (device 0x000000FF)
   ```
   This shows the driver has added the `can0` interface. You may see `can1`, `can2`, etc.

2. **Configure CAN interface (250 kbps baud):**

   ```bash
   sudo ip link set can0 type can bitrate 250000
   sudo ip link set can0 up
   ```

3. **Verify interface:**

   ```bash
   # Show can0 link status, should say "UP".
   ip link show can0
   # Monitor some CAN traffic, should see some frames. Ctrl-C to exit.
   candump can0  
   ```

### Windows Setup

TODO: not tested

### macOS Setup

TODO: not tested

## Troubleshooting

### 
**Load kernel modules:**

```bash
sudo modprobe can
sudo modprobe can_raw
# For USB-serial CAN adapters, you may need slcan
sudo modprobe slcan  
```

### Python error: No module named 'can'

If you are using the python virtual environment, activate it by running the included script:
```bash
source sourceme.sh
```

Otherwise, install python-can:

```bash
pip install python-can
```

### "RTNETLINK answers: Operation not permitted"

Run with sudo or add user to netdev group:

```bash
sudo usermod -a -G netdev $USER
# Log out and back in
```

### No CAN communcations

1. Bring up CAN interface. See steps above for SocketCan.
1. Check bitrate matches (250 kbps for NMEA2000)
2. Verify CAN termination (120Ω at both ends)
3. Check cable connections (CAN-H, CAN-L, GND)
4. Use `candump can0` to verify CAN interface works

## Protocol Details

The protocol is defined here:

TODO: add link to protocol document


## Contributing

This is a reference implementation for third-party integration. For issues or suggestions:

- Open a GitHub issue or Pull-Request on this repository
- For professional support, contact support@lumiteclighting.com

## License

Reference implementation provided for third-party integration with Lumitec Poco devices. This example code is in the public domain.

