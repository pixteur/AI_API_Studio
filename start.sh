#!/bin/bash
# Nano Banana Studio — macOS / Linux launcher
# Usage: double-click or run ./start.sh in Terminal

cd "$(dirname "$0")"

echo ""
echo "  Nano Banana Studio 1.0 beta"
echo "  ============================"
echo ""

# Check Python 3 is available
if ! command -v python3 &> /dev/null; then
    echo "  ERROR: Python 3 not found."
    echo "  Download Python 3.11 from https://python.org/downloads"
    echo ""
    read -p "Press Enter to exit..."
    exit 1
fi

python3 nbs.py

# Keep terminal open if it crashes
if [ $? -ne 0 ]; then
    echo ""
    echo "  The app exited with an error. See above for details."
    read -p "Press Enter to exit..."
fi
