#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://127.0.0.1:8000/api/v1}"
DATA_DIR="${DATA_DIR:-}"
SEMAG_PRELOAD='["2018-Q1","2018-Q2","2018-Q3","2018-Q4"]'
FULL_PRELOAD='["2018-Q1","2018-Q2","2018-Q3","2018-Q4","2019-Q1","2019-Q2","2019-Q3","2019-Q4","2020-Q1","2020-Q2","2020-Q3","2020-Q4","2021-Q1","2021-Q2","2021-Q3","2021-Q4","2022-Q1","2022-Q2","2022-Q3","2022-Q4","2023-Q1","2023-Q2","2023-Q3","2023-Q4"]'

usage() {
  cat <<USAGE
Usage: scripts/bootstrap-two-drug-demo.sh [options]

Options:
  --api-base <url>       Backend API base (default: http://127.0.0.1:8000/api/v1)
  --data-dir <path>      Data directory path as seen by the backend process
  --help                 Show this help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --api-base)
      API_BASE="$2"
      shift 2
      ;;
    --data-dir)
      DATA_DIR="$2"
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

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing command: $1" >&2
    exit 1
  fi
}

require_cmd python3

seed_drug() {
  local drug_id="$1"
  local preload_json="$2"
  local data_dir="${DATA_DIR:-}"

  python3 - "${API_BASE}" "${drug_id}" "${preload_json}" "${data_dir}" <<'PY'
import json
import sys
from urllib import request

api_base, drug_id, preload_json, data_dir = sys.argv[1:5]
payload = {
    "drug_ids": [drug_id],
    "preload_quarters": json.loads(preload_json),
}
if data_dir:
    payload["data_dir"] = data_dir

body = json.dumps(payload).encode("utf-8")
req = request.Request(
    f"{api_base}/admin/seed-demo",
    data=body,
    headers={"Content-Type": "application/json"},
    method="POST",
)
with request.urlopen(req, timeout=600) as resp:
    sys.stdout.write(resp.read().decode("utf-8"))
PY
}

seed_drug "semaglutide" "$SEMAG_PRELOAD" >/dev/null
seed_drug "minoxidil" "$FULL_PRELOAD" >/dev/null

echo "Seeded semaglutide baseline and full-history minoxidil."
