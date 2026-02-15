#!/bin/bash
# GradeSense Backend - Startup Script

set -e

echo "🚀 Starting GradeSense Backend..."

# Activate venv
source .venv/bin/activate

# Start the backend server
exec uvicorn main:app --reload --host 0.0.0.0 --port 8000
