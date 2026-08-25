#!/bin/bash

# Navigate to script directory regardless of where it's called from
cd "$(dirname "$0")"

echo ""
echo "====================================="
echo "   Order Validation App — Launcher"
echo "====================================="
echo ""

# Step 1: Install dependencies (skips quietly if already installed)
echo "📦 Checking dependencies..."
pip3 install -r requirements.txt -q
echo "   Dependencies OK ✅"
echo ""

# Step 2: Launch the app
echo "🚀 Launching Order Validation App..."
echo "   Opening at http://localhost:8501"
echo "   Select QA or UAT environment in the app sidebar."
echo ""
streamlit run streamlit_app.py
