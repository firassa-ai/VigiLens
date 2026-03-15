#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${ROOT_DIR}/data/real"
API_BASE="${API_BASE:-http://127.0.0.1:8000/api/v1}"
DO_FETCH=1
FETCH_MODE="sample"
BACKEND_DATA_DIR=""
BACKEND_CONTAINER=""

usage() {
  cat <<USAGE
Usage: scripts/real-data-smoke.sh [options]

Options:
  --data-dir <path>      Data directory to seed from (default: data/real)
  --backend-data-dir <path>
                         Data directory path as seen by backend process
                         (default: same as --data-dir)
  --backend-container <name>
                         Optional container name; copies NDJSON files into backend
                         before seeding using --backend-data-dir path.
  --api-base <url>       Backend API base (default: http://127.0.0.1:8000/api/v1)
  --fetch-mode <mode>    sample|large (default: sample)
  --skip-fetch           Skip fetch step and reuse existing NDJSON files
  --help                 Show this help

Requirements:
- Backend running locally and reachable at API base URL.
- /api/v1/admin/seed-demo available (DEMO_MODE=true).
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --data-dir)
      DATA_DIR="$2"
      shift 2
      ;;
    --backend-data-dir)
      BACKEND_DATA_DIR="$2"
      shift 2
      ;;
    --backend-container)
      BACKEND_CONTAINER="$2"
      shift 2
      ;;
    --api-base)
      API_BASE="$2"
      shift 2
      ;;
    --fetch-mode)
      FETCH_MODE="$2"
      shift 2
      ;;
    --skip-fetch)
      DO_FETCH=0
      shift
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing command: $1" >&2
    exit 1
  fi
}

require_cmd curl
require_cmd jq

if [[ "$FETCH_MODE" != "sample" && "$FETCH_MODE" != "large" ]]; then
  echo "--fetch-mode must be 'sample' or 'large'" >&2
  exit 1
fi

if [[ -z "$BACKEND_DATA_DIR" ]]; then
  BACKEND_DATA_DIR="$DATA_DIR"
fi

if [[ "$DO_FETCH" -eq 1 ]]; then
  if [[ "$FETCH_MODE" == "large" ]]; then
    echo "Fetching openFDA large dataset into $DATA_DIR"
    "${ROOT_DIR}/scripts/fetch-real-large-data.sh" --data-dir "$DATA_DIR"
  else
    echo "Fetching openFDA sample data into $DATA_DIR"
    "${ROOT_DIR}/scripts/fetch-real-sample-data.sh" --data-dir "$DATA_DIR"
  fi
fi

if [[ ! -s "$DATA_DIR/semaglutide.ndjson" || ! -s "$DATA_DIR/minoxidil.ndjson" ]]; then
  echo "Missing required data files in $DATA_DIR" >&2
  exit 1
fi

if [[ -n "$BACKEND_CONTAINER" ]]; then
  require_cmd docker
  docker exec "$BACKEND_CONTAINER" mkdir -p "$BACKEND_DATA_DIR"
  docker cp "$DATA_DIR/semaglutide.ndjson" "$BACKEND_CONTAINER:$BACKEND_DATA_DIR/semaglutide.ndjson"
  docker cp "$DATA_DIR/minoxidil.ndjson" "$BACKEND_CONTAINER:$BACKEND_DATA_DIR/minoxidil.ndjson"
fi

echo "Checking backend health..."
curl -fsS "$API_BASE/health" >/dev/null

echo "Seeding backend from real sample data..."
"${ROOT_DIR}/scripts/bootstrap-two-drug-demo.sh" --api-base "$API_BASE" --data-dir "$BACKEND_DATA_DIR"

echo "Checking ingest status..."
status_resp="$(curl -fsS "$API_BASE/ingest/status?drug_id=semaglutide")"
echo "$status_resp" | jq '{quarters_loaded: (.quarters_loaded | length), next_quarter, total_reports_loaded}'
minoxidil_status_resp="$(curl -fsS "$API_BASE/ingest/status?drug_id=minoxidil")"
echo "$minoxidil_status_resp" | jq '{drug:"minoxidil", quarters_loaded: (.quarters_loaded | length), next_quarter, total_reports_loaded}'

echo "Checking timeline size..."
timeline_count="$(curl -fsS "$API_BASE/drugs/semaglutide/timeline" | jq 'length')"
echo "timeline points: $timeline_count"

next_q="$(echo "$status_resp" | jq -r '.next_quarter')"
if [[ "$next_q" != "null" ]]; then
  echo "Ingesting one additional quarter ($next_q) for smoke validation..."
  curl -fsS -X POST "$API_BASE/ingest/next-quarter" -H 'Content-Type: application/json' -d '{"drug_id":"semaglutide"}' | jq '{next_quarter, total_reports_loaded}'
else
  echo "No additional quarter available after seed preload; skipping extra ingest call."
fi

signals_count="$(curl -fsS "$API_BASE/drugs/semaglutide/signals" | jq 'length')"
echo "active signals rows: $signals_count"
minoxidil_casefile="$(curl -fsS "$API_BASE/drugs/minoxidil/casefile-summary")"
echo "$minoxidil_casefile" | jq '{drug:"minoxidil", proof_backed_signals, active_quarter}'

echo "Real-data smoke validation completed."
