#!/bin/bash
set -e

# Use the existing virtual environment
if [ ! -d "venv" ]; then
    echo "Virtual environment not found. Please run: python3 -m venv venv && ./venv/bin/pip install -r requirements.txt"
    exit 1
fi

export GOOGLE_CLOUD_PROJECT=genai-demo-386410
export GOOGLE_CLOUD_REGION=us-central1

# Run the app
echo "Starting Gemini TTS App..."
./venv/bin/python main.py
