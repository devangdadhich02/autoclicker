#!/usr/bin/env bash
# Velora Auto Clicker — VPS Deployment Script
# Usage: ./deploy.sh [--pull] [--migrate] [--restart]
set -euo pipefail

PULL=false
MIGRATE=false
RESTART=false

for arg in "$@"; do
  case $arg in
    --pull) PULL=true ;;
    --migrate) MIGRATE=true ;;
    --restart) RESTART=true ;;
  esac
done

echo "==> Velora Deploy Script"

if $PULL; then
  echo "  -> Pulling latest code..."
  git pull origin main
fi

echo "  -> Building Docker images..."
docker compose build --no-cache

if $MIGRATE; then
  echo "  -> Running Alembic migrations..."
  docker compose run --rm backend alembic upgrade head
fi

if $RESTART; then
  echo "  -> Stopping existing containers..."
  docker compose down
fi

echo "  -> Starting services..."
docker compose up -d

echo "  -> Waiting for backend health check..."
for i in $(seq 1 30); do
  if curl -sf http://localhost:8000/api/v1/health/ping > /dev/null 2>&1; then
    echo "  -> Backend healthy!"
    break
  fi
  echo "     Attempt $i/30..."
  sleep 3
done

echo "==> Deployment complete."
docker compose ps
