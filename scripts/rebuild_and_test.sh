#!/bin/bash
set -e

echo "================================"
echo "REM Migration Rebuild & Test"
echo "================================"

echo ""
echo "[1/6] Stopping and removing Docker containers..."
docker rm -f rem-postgres 2>/dev/null || true
docker volume rm rem_postgres_data 2>/dev/null || true

echo ""
echo "[2/6] Starting fresh PostgreSQL with updated migrations..."
docker compose up -d postgres
echo "Waiting for PostgreSQL to be ready..."
sleep 12

echo ""
echo "[3/6] Verifying rem_lookup function signature..."
docker exec rem-postgres psql -U rem -d rem -c "\df rem_lookup"

echo ""
echo "[4/6] Verifying rem_fuzzy function signature..."
docker exec rem-postgres psql -U rem -d rem -c "\df rem_fuzzy"

echo ""
echo "[5/6] Loading seed data..."
source .venv/bin/activate
rem db load tests/data/seed/test-user-data.yaml --user-id test-user

echo ""
echo "[6/6] Running end-to-end agent test..."
python test_tool_debugging.py 2>&1 | grep -E "(QUERY|MESSAGE|Tool:|Content:|FINAL)" | head -50

echo ""
echo "================================"
echo "✅ Rebuild Complete!"
echo "================================"
