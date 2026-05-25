#!/bin/sh
set -e

echo "================================================"
echo " Velora Auto Clicker — Backend Starting"
echo "================================================"

echo "[1/3] Running Alembic database migrations..."
alembic upgrade head
echo "      Migrations done."

echo "[2/3] Starting Uvicorn server..."
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 2 \
    --loop uvloop \
    --access-log
