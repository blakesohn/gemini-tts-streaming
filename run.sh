#!/bin/bash
set -e

# Use the existing virtual environment
if [ ! -d "venv" ]; then
    echo "Virtual environment not found. Please run: python3 -m venv venv && ./venv/bin/pip install -r requirements.txt"
    exit 1
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

# Run the app
echo "Starting Gemini TTS App..."
echo "Project: $GOOGLE_CLOUD_PROJECT"
echo "Region: $GOOGLE_CLOUD_REGION"
./venv/bin/python main.py
