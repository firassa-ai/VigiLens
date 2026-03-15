#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${ROOT_DIR}/data/real"
START_DATE="20180101"
END_DATE="20231231"
SEMA_REPORTS=400
MINOXIDIL_REPORTS=5000

usage() {
  cat <<USAGE
Usage: scripts/fetch-real-sample-data.sh [options]

Options:
  --data-dir <path>      Output directory (default: data/real)
  --start <YYYYMMDD>     Start date inclusive (default: 20180101)
  --end <YYYYMMDD>       End date inclusive (default: 20231231)
  --help                 Show this help
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

"${ROOT_DIR}/scripts/fetch-openfda-sample.sh" \
  --drug semaglutide \
  --start "$START_DATE" \
  --end "$END_DATE" \
  --max-reports "$SEMA_REPORTS" \
  --out "$DATA_DIR/semaglutide.ndjson"

"${ROOT_DIR}/scripts/fetch-openfda-sample.sh" \
  --drug minoxidil \
  --start "$START_DATE" \
  --end "$END_DATE" \
  --max-reports "$MINOXIDIL_REPORTS" \
  --out "$DATA_DIR/minoxidil.ndjson"

wc -l "$DATA_DIR/semaglutide.ndjson" "$DATA_DIR/minoxidil.ndjson"
