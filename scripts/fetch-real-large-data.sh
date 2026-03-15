#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${ROOT_DIR}/data/real-large"
START_DATE="20180101"
END_DATE="20231231"
SEMA_REPORTS=20000
MINOXIDIL_REPORTS=30000
WINDOW_MODE="month"

usage() {
  cat <<USAGE
Usage: scripts/fetch-real-large-data.sh [options]

Fetches larger real-data NDJSON datasets suitable for stress testing.

Options:
  --data-dir <path>      Output directory (default: data/real-large)
  --start <YYYYMMDD>     Start date inclusive (default: 20180101)
  --end <YYYYMMDD>       End date inclusive (default: 20231231)
  --sema-reports <n>     Max semaglutide rows after dedupe (default: 20000)
  --minoxidil-reports <n>
                         Max minoxidil rows after dedupe (default: 30000)
  --window <mode>        quarter|month (default: month)
  --help                 Show this help

Environment:
  OPENFDA_API_KEY        Strongly recommended for larger pulls.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --data-dir)
      DATA_DIR="$2"
      shift 2
      ;;
    --start)
      START_DATE="$2"
      shift 2
      ;;
    --end)
      END_DATE="$2"
      shift 2
      ;;
    --sema-reports)
      SEMA_REPORTS="$2"
      shift 2
      ;;
    --minoxidil-reports)
      MINOXIDIL_REPORTS="$2"
      shift 2
      ;;
    --window)
      WINDOW_MODE="$2"
      shift 2
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

mkdir -p "$DATA_DIR"

"${ROOT_DIR}/scripts/fetch-openfda-bulk.sh" \
  --drug semaglutide \
  --start "$START_DATE" \
  --end "$END_DATE" \
  --max-reports "$SEMA_REPORTS" \
  --window "$WINDOW_MODE" \
  --out "$DATA_DIR/semaglutide.ndjson"

"${ROOT_DIR}/scripts/fetch-openfda-bulk.sh" \
  --drug minoxidil \
  --start "$START_DATE" \
  --end "$END_DATE" \
  --max-reports "$MINOXIDIL_REPORTS" \
  --window "$WINDOW_MODE" \
  --out "$DATA_DIR/minoxidil.ndjson"

wc -l "$DATA_DIR/semaglutide.ndjson" "$DATA_DIR/minoxidil.ndjson"
