#!/bin/sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

echo "Waiting for backend health..."
until curl -fsS http://backend:8000/api/v1/health >/dev/null 2>&1; do
  sleep 2
done

echo "Seeding demo data..."
"${SCRIPT_DIR}/bootstrap-two-drug-demo.sh" --api-base "http://backend:8000/api/v1" >/dev/null

echo "Seed complete (semaglutide baseline + shipped minoxidil proof-backed fixture)."
