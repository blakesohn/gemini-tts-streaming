#!/bin/bash
set -e

# Setup venv if needed
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    ./venv/bin/pip install -r requirements.txt -i https://pypi.org/simple
else
    # Install any new requirements
    echo "Checking dependencies..."
    ./venv/bin/pip install -r requirements.txt -i https://pypi.org/simple
fi

export GOOGLE_CLOUD_PROJECT=genai-demo-386410
export GOOGLE_CLOUD_REGION=us-central1

echo "Starting Web Application..."
echo "Open http://127.0.0.1:8001 in your browser"
./venv/bin/uvicorn app:app --reload --host 0.0.0.0 --port 8001
