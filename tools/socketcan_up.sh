#!/bin/bash
# Script to bring up a SocketCAN interface for Poco CAN on Linux
# Assumes can0 interface and 250kbps bitrate for NMEA 2000 standard

# Usage: sudo ./socketcan_up.sh

INTERFACE="can0"
BITRATE="250000"

sudo ip link set $INTERFACE down
sudo ip link set $INTERFACE type can bitrate $BITRATE
sudo ip link set $INTERFACE up

ip link show $INTERFACE
