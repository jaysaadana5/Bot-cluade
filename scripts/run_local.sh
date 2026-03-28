#!/bin/bash
# Run locally without Docker for development
set -e

echo "=== Starting Polymarket BTC Bot (Local Dev) ==="

# Check .env
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env - edit with your API keys."
fi

# Backend
echo "Starting backend..."
cd backend
python -m venv venv 2>/dev/null || true
source venv/bin/activate
pip install -r requirements.txt -q
cd ..
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# Frontend
echo "Starting frontend..."
cd frontend
npm install -q
npm start &
FRONTEND_PID=$!

cd ..
echo ""
echo "Backend:  http://localhost:8000"
echo "Frontend: http://localhost:3000"
echo ""

# Cleanup on exit
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT
wait
