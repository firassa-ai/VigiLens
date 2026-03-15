#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_BASE="${API_BASE:-http://127.0.0.1:8000/api/v1}"
OUT_DIR="${ROOT_DIR}/results/demo-smoke-latest"
SUMMARY_PATH="${OUT_DIR}/summary.md"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

require_cmd curl
require_cmd jq
require_cmd docker

post_next_quarter() {
  local output_path="$1"
  local http_code
  http_code="$(
    curl -sS -o "${output_path}" -w '%{http_code}' -X POST "${API_BASE}/ingest/next-quarter" \
      -H 'Content-Type: application/json' \
      -d '{"drug_id":"semaglutide"}'
  )"
  case "${http_code}" in
    200)
      return 0
      ;;
    409)
      return 9
      ;;
    *)
      echo "Unexpected ingest/next-quarter response: HTTP ${http_code}" >&2
      if [[ -s "${output_path}" ]]; then
        cat "${output_path}" >&2
      fi
      return 1
      ;;
  esac
}

mkdir -p "${OUT_DIR}"

echo "# Demo Smoke" >"${SUMMARY_PATH}"
echo >>"${SUMMARY_PATH}"
echo "- Generated: $(date '+%Y-%m-%d %H:%M:%S %Z')" >>"${SUMMARY_PATH}"
echo "- API base: ${API_BASE}" >>"${SUMMARY_PATH}"

docker compose ps >>"${TMP_DIR}/docker-ps.txt"
{
  echo
  echo "## Docker"
  sed 's/^/- /' "${TMP_DIR}/docker-ps.txt"
} >>"${SUMMARY_PATH}"

echo "Waiting for ${API_BASE}/health ..."
for _ in $(seq 1 60); do
  if curl -fsS "${API_BASE}/health" >"${TMP_DIR}/health.json"; then
    break
  fi
  sleep 2
done

if [[ ! -s "${TMP_DIR}/health.json" ]]; then
  echo "Health check did not succeed." >&2
  exit 1
fi

curl -fsS "${API_BASE}/drugs" >"${TMP_DIR}/drugs.json"

echo "Waiting for compose seed service to finish before reseeding..."
docker compose wait seed >/dev/null 2>&1 || true

curl -fsS "${API_BASE}/ingest/status?drug_id=semaglutide" >"${TMP_DIR}/ingest-status.json"
curl -fsS "${API_BASE}/ingest/status?drug_id=minoxidil" >"${TMP_DIR}/minoxidil-ingest-status.json"
baseline_quarter="$(jq -r '.quarters_loaded[-1] // empty' "${TMP_DIR}/ingest-status.json")"
minoxidil_quarter="$(jq -r '.quarters_loaded[-1] // empty' "${TMP_DIR}/minoxidil-ingest-status.json")"

if [[ "${baseline_quarter}" == "2018-Q4" && "${minoxidil_quarter}" == "2023-Q4" ]]; then
  echo "Using compose-seeded deterministic baseline preload."
else
  echo "Resetting to deterministic baseline preload..."
  "${ROOT_DIR}/scripts/bootstrap-two-drug-demo.sh" --api-base "${API_BASE}" >"${TMP_DIR}/seed.txt"
  curl -fsS "${API_BASE}/ingest/status?drug_id=semaglutide" >"${TMP_DIR}/ingest-status.json"
  curl -fsS "${API_BASE}/ingest/status?drug_id=minoxidil" >"${TMP_DIR}/minoxidil-ingest-status.json"
  baseline_quarter="$(jq -r '.quarters_loaded[-1] // empty' "${TMP_DIR}/ingest-status.json")"
  minoxidil_quarter="$(jq -r '.quarters_loaded[-1] // empty' "${TMP_DIR}/minoxidil-ingest-status.json")"
fi

latest_quarter="$(jq -r '.quarters_loaded[-1] // empty' "${TMP_DIR}/ingest-status.json")"
next_quarter="$(jq -r '.next_quarter // empty' "${TMP_DIR}/ingest-status.json")"

if [[ -z "${latest_quarter}" ]]; then
  echo "No loaded semaglutide quarter found." >&2
  exit 1
fi

echo "Driving semaglutide ingest to the reveal quarter (2023-Q3)..."
reveal_loop_guard=0
while [[ "${reveal_loop_guard}" -lt 200 ]]; do
  latest_quarter="$(jq -r '.quarters_loaded[-1] // empty' "${TMP_DIR}/ingest-status.json")"
  next_quarter="$(jq -r '.next_quarter // empty' "${TMP_DIR}/ingest-status.json")"
  if [[ "${latest_quarter}" == "2023-Q3" || -z "${next_quarter}" || "${next_quarter}" == "null" ]]; then
    break
  fi
  echo "  -> ingesting ${next_quarter}"
  status_code=0
  post_next_quarter "${TMP_DIR}/ingest-step.json" || status_code=$?
  if [[ "${status_code}" -eq 9 ]]; then
    echo "     ingest still consolidating; retrying..."
    sleep 2
    curl -fsS "${API_BASE}/ingest/status?drug_id=semaglutide" >"${TMP_DIR}/ingest-status.json"
    continue
  fi
  if [[ "${status_code}" -ne 0 ]]; then
    exit 1
  fi
  curl -fsS "${API_BASE}/ingest/status?drug_id=semaglutide" >"${TMP_DIR}/ingest-status.json"
  latest_quarter="$(jq -r '.quarters_loaded[-1] // empty' "${TMP_DIR}/ingest-status.json")"
  echo "     reached ${latest_quarter}"
  reveal_loop_guard=$((reveal_loop_guard + 1))
done

if jq -e '.quarters_loaded | index("2023-Q3")' "${TMP_DIR}/ingest-status.json" >/dev/null 2>&1; then
  reveal_quarter="2023-Q3"
else
  reveal_quarter="$(jq -r '.quarters_loaded[-1] // empty' "${TMP_DIR}/ingest-status.json")"
  echo "Expected semaglutide ingest history to include 2023-Q3, got ${reveal_quarter}." >&2
  exit 1
fi

query_payload="$(jq -n --arg q "${reveal_quarter}" '{drug_id:"semaglutide",question_text:"Which old reports were reinterpreted as precursor evidence?",quarter_context:$q}')"
curl -fsS -X POST "${API_BASE}/query" -H 'Content-Type: application/json' -d "${query_payload}" >"${TMP_DIR}/query-reveal.json"

echo "Advancing one step to the FDA receipt quarter (2023-Q4)..."
validation_loop_guard=0
while [[ "${validation_loop_guard}" -lt 40 ]]; do
  latest_quarter="$(jq -r '.quarters_loaded[-1] // empty' "${TMP_DIR}/ingest-status.json")"
  next_quarter="$(jq -r '.next_quarter // empty' "${TMP_DIR}/ingest-status.json")"
  if [[ "${latest_quarter}" == "2023-Q4" || -z "${next_quarter}" || "${next_quarter}" == "null" ]]; then
    break
  fi
  echo "  -> ingesting ${next_quarter}"
  status_code=0
  post_next_quarter "${TMP_DIR}/ingest-step-validation.json" || status_code=$?
  if [[ "${status_code}" -eq 9 ]]; then
    echo "     ingest still consolidating; retrying..."
    sleep 2
    curl -fsS "${API_BASE}/ingest/status?drug_id=semaglutide" >"${TMP_DIR}/ingest-status.json"
    continue
  fi
  if [[ "${status_code}" -ne 0 ]]; then
    exit 1
  fi
  curl -fsS "${API_BASE}/ingest/status?drug_id=semaglutide" >"${TMP_DIR}/ingest-status.json"
  latest_quarter="$(jq -r '.quarters_loaded[-1] // empty' "${TMP_DIR}/ingest-status.json")"
  echo "     reached ${latest_quarter}"
  validation_loop_guard=$((validation_loop_guard + 1))
done

curl -fsS "${API_BASE}/drugs/semaglutide/episodes" >"${TMP_DIR}/episodes.json"
curl -fsS "${API_BASE}/beliefs/semaglutide" >"${TMP_DIR}/beliefs.json"
curl -fsS "${API_BASE}/drugs/semaglutide/scorecard" >"${TMP_DIR}/scorecard.json"
curl -fsS "${API_BASE}/drugs/minoxidil/casefile-summary" >"${TMP_DIR}/minoxidil-casefile.json"

latest_quarter="$(jq -r '.quarters_loaded[-1] // empty' "${TMP_DIR}/ingest-status.json")"
minoxidil_latest_quarter="$(jq -r '.quarters_loaded[-1] // empty' "${TMP_DIR}/minoxidil-ingest-status.json")"

health_ok="$(jq -r '.ok and .postgres_ok' "${TMP_DIR}/health.json")"
quarters_loaded="$(jq '.quarters_loaded | length' "${TMP_DIR}/ingest-status.json")"
reports_loaded="$(jq '.total_reports_loaded' "${TMP_DIR}/ingest-status.json")"
episodes_count="$(jq 'length' "${TMP_DIR}/episodes.json")"
beliefs_count="$(jq 'length' "${TMP_DIR}/beliefs.json")"
scorecard_count="$(jq 'length' "${TMP_DIR}/scorecard.json")"
validated_count="$(jq '[.[] | select(.result == "validated")] | length' "${TMP_DIR}/scorecard.json")"
reveal_query_evidence_count="$(jq '.evidence | length' "${TMP_DIR}/query-reveal.json")"
reveal_query_memory_count="$(jq '.episodic_context | length' "${TMP_DIR}/query-reveal.json")"
minoxidil_proof_backed_count="$(jq '.proof_backed_signals' "${TMP_DIR}/minoxidil-casefile.json")"

{
  echo
  echo "## Checks"
  echo "- health_ok: ${health_ok}"
  echo "- baseline_quarter: ${baseline_quarter}"
  echo "- reveal_quarter: ${reveal_quarter}"
  echo "- latest_quarter: ${latest_quarter}"
  echo "- quarters_loaded: ${quarters_loaded}"
  echo "- reports_loaded: ${reports_loaded}"
  echo "- episodes_count: ${episodes_count}"
  echo "- beliefs_count: ${beliefs_count}"
  echo "- scorecard_count: ${scorecard_count}"
  echo "- validated_count: ${validated_count}"
  echo "- reveal_query_evidence_count: ${reveal_query_evidence_count}"
  echo "- reveal_query_memory_count: ${reveal_query_memory_count}"
  echo "- minoxidil_latest_quarter: ${minoxidil_latest_quarter}"
  echo "- minoxidil_proof_backed_count: ${minoxidil_proof_backed_count}"
} >>"${SUMMARY_PATH}"

if [[ "${health_ok}" != "true" ]]; then
  echo "Health endpoint is not fully ready." >&2
  exit 1
fi

if [[ "${quarters_loaded}" -lt 4 ]]; then
  echo "Expected at least baseline quarters to be loaded." >&2
  exit 1
fi

if [[ "${baseline_quarter}" != "2018-Q4" ]]; then
  echo "Expected deterministic baseline preload to stop at 2018-Q4, got ${baseline_quarter}." >&2
  exit 1
fi

if [[ "${reveal_quarter}" != "2023-Q3" ]]; then
  echo "Expected reveal quarter 2023-Q3, got ${reveal_quarter}." >&2
  exit 1
fi

if [[ "${latest_quarter}" != "2023-Q4" ]]; then
  echo "Expected semaglutide ingest to reach the FDA receipt quarter 2023-Q4, got ${latest_quarter}." >&2
  exit 1
fi

if [[ "${minoxidil_latest_quarter}" != "2023-Q4" ]]; then
  echo "Expected minoxidil to be fully preloaded through 2023-Q4, got ${minoxidil_latest_quarter}." >&2
  exit 1
fi

if [[ "${reports_loaded}" -lt 2000 ]]; then
  echo "Expected the public semaglutide baseline to exceed 2,000 reports." >&2
  exit 1
fi

if [[ "${episodes_count}" -lt 1 || "${beliefs_count}" -lt 1 || "${scorecard_count}" -lt 1 ]]; then
  echo "Expected episodes, beliefs, and scorecard entries to be present." >&2
  exit 1
fi

if [[ "${reveal_query_evidence_count}" -lt 1 || "${reveal_query_memory_count}" -lt 1 ]]; then
  echo "Expected the reveal-quarter query to return both evidence and episodic memory context." >&2
  exit 1
fi

if [[ "${minoxidil_proof_backed_count}" -lt 1 ]]; then
  echo "Expected minoxidil to expose proof-backed casefile signals." >&2
  exit 1
fi

echo
echo "Demo smoke passed."
echo "Summary: ${SUMMARY_PATH}"
