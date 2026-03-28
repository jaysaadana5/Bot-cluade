#!/bin/bash
# Polymarket BTC Trading Bot - VPS Deployment Script
set -e

echo "=== Polymarket BTC Trading Bot - Deploy ==="

# Check prerequisites
command -v docker >/dev/null 2>&1 || { echo "Docker required. Install: curl -fsSL https://get.docker.com | sh"; exit 1; }
command -v docker-compose >/dev/null 2>&1 || command -v docker compose >/dev/null 2>&1 || { echo "Docker Compose required."; exit 1; }

# Check .env
if [ ! -f .env ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
    echo "IMPORTANT: Edit .env with your API keys before starting!"
    echo "  nano .env"
    exit 1
fi

# Build and start
echo "Building containers..."
docker compose build

echo "Starting services..."
docker compose up -d

echo ""
echo "=== Deployment Complete ==="
echo "Frontend:  http://localhost:3000"
echo "API:       http://localhost:8000"
echo "Health:    http://localhost:8000/health"
echo ""
echo "Commands:"
echo "  docker compose logs -f        # View logs"
echo "  docker compose restart         # Restart"
echo "  docker compose down            # Stop"
echo "  docker compose up -d --build   # Rebuild & restart"
