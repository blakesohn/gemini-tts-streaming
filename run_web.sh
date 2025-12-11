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

# Load environment variables from .env if it exists
if [ -f ".env" ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Check if GOOGLE_CLOUD_PROJECT is set
if [ -z "$GOOGLE_CLOUD_PROJECT" ]; then
    echo "Error: GOOGLE_CLOUD_PROJECT is not set."
    echo "Please either:"
    echo "  1. Copy .env.example to .env and set your project ID"
    echo "  2. Export GOOGLE_CLOUD_PROJECT environment variable"
    exit 1
fi

# Set default region if not specified
export GOOGLE_CLOUD_REGION=${GOOGLE_CLOUD_REGION:-us-central1}

echo "Starting Web Application..."
echo "Project: $GOOGLE_CLOUD_PROJECT"
echo "Region: $GOOGLE_CLOUD_REGION"
echo "Open http://127.0.0.1:8001 in your browser"
./venv/bin/uvicorn app:app --reload --host 0.0.0.0 --port 8001
