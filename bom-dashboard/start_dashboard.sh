#!/bin/bash
# HEQA BOM & Inventory Dashboard — Linux startup script
# Usage: ./start_dashboard.sh

cd "$(dirname "$0")"

# Check Python is available
if ! command -v python3 &> /dev/null; then
    echo "ERROR: python3 not found. Install it with: sudo apt install python3 python3-pip"
    exit 1
fi

# Install dependencies if needed
if ! python3 -c "import streamlit" &> /dev/null; then
    echo "Installing dependencies..."
    pip3 install -r requirements.txt
fi

echo "Starting HEQA BOM Dashboard on http://localhost:8501"
python3 -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501
