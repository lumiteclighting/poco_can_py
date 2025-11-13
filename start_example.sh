#!/bin/bash
#
# Lumitec Poco CAN Examples Launcher Script
#
# This script launches the Poco CAN Examples Launcher GUI.

# Color codes for output (can be reused by sourcing scripts)
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"

# Load the virtual environment
source "$PROJECT_DIR/sourceme.sh"

# Launch the Poco CAN Demo GUI
echo -e "${BLUE}Starting Poco CAN Demo GUI...${NC}"
python3 "$PROJECT_DIR/example_launcher.py"
