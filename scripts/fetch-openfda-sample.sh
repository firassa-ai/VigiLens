#!/usr/bin/env bash
set -euo pipefail

OPENFDA_URL="https://api.fda.gov/drug/event.json"
DRUG_ID="semaglutide"
START_DATE="20180101"
END_DATE="20231231"
MAX_REPORTS=300
OUT_PATH=""

usage() {
  cat <<USAGE
Usage: scripts/fetch-openfda-sample.sh [options]

Options:
  --drug <name>          Generic drug name (default: semaglutide)
  --start <YYYYMMDD>     Start date inclusive (default: 20180101)
  --end <YYYYMMDD>       End date inclusive (default: 20231231)
  --max-reports <n>      Maximum transformed records to write (default: 300)
  --out <path>           Output NDJSON path (default: data/real/<drug>.ndjson)
  --help                 Show this help

Environment:
  OPENFDA_API_KEY        Optional openFDA API key for higher daily quota.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --drug)
      DRUG_ID="$2"
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
    --max-reports)
      MAX_REPORTS="$2"
      shift 2
      ;;
    --out)
      OUT_PATH="$2"
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

require_cmd curl
require_cmd jq

if [[ -z "$OUT_PATH" ]]; then
  ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  OUT_PATH="${ROOT_DIR}/data/real/${DRUG_ID}.ndjson"
fi

mkdir -p "$(dirname "$OUT_PATH")"
: > "$OUT_PATH"

DRUG_LOWER="$(printf '%s' "$DRUG_ID" | tr '[:upper:]' '[:lower:]')"
SEARCH_EXPR="patient.drug.openfda.generic_name:${DRUG_ID} AND receivedate:[${START_DATE} TO ${END_DATE}]"

skip=0
collected=0

while (( collected < MAX_REPORTS )); do
  remaining=$((MAX_REPORTS - collected))
  limit=$(( remaining > 100 ? 100 : remaining ))
  tmp_json="$(mktemp)"

  curl_args=(
    -sS
    --get
    --connect-timeout 10
    --max-time 45
    --retry 2
    --retry-delay 1
    --retry-all-errors
    "$OPENFDA_URL"
    --data-urlencode "search=${SEARCH_EXPR}"
    --data-urlencode "limit=${limit}"
    --data-urlencode "skip=${skip}"
  )

  if [[ -n "${OPENFDA_API_KEY:-}" ]]; then
    curl_args+=(--data-urlencode "api_key=${OPENFDA_API_KEY}")
  fi

  http_code="$(curl "${curl_args[@]}" -o "$tmp_json" -w '%{http_code}')"
  if [[ "$http_code" == "404" ]]; then
    rm -f "$tmp_json"
    break
  fi
  if [[ "$http_code" -ge 400 ]]; then
    rm -f "$tmp_json"
    echo "openFDA request failed at skip=${skip} (HTTP ${http_code})" >&2
    exit 1
  fi

  page_results="$(jq '.results | length // 0' "$tmp_json")"
  if [[ "$page_results" -eq 0 ]]; then
    rm -f "$tmp_json"
    break
  fi

  appended="$({
    jq -cr \
      --arg drug_id "$DRUG_ID" \
      --arg drug_lower "$DRUG_LOWER" \
      '
      def role_from_code:
        ((.drugcharacterization // "") | tostring) as $c
        | if ($c == "1" or $c == "2") then "suspect"
          elif $c == "3" then "concomitant"
          elif $c == "4" then "interacting"
          else "unknown"
          end;

      def normalize_sex:
        if (.patient.patientsex // "") == "1" then "male"
        elif (.patient.patientsex // "") == "2" then "female"
        else "unknown"
        end;

      def normalize_age:
        ((.patient.patientonsetage // null) | tonumber?) as $age
        | if ($age != null and $age >= 0 and $age <= 120) then $age else null end;

      def normalize_date:
        if ((.receivedate // "") | type) == "string" and ((.receivedate // "") | length) == 8
        then "\(.receivedate[0:4])-\(.receivedate[4:6])-\(.receivedate[6:8])"
        else null
        end;

      def outcomes:
        [
          if .seriousnessdeath == "1" then "death" else empty end,
          if .seriousnesshospitalization == "1" then "hospitalization" else empty end,
          if .seriousnesslifethreatening == "1" then "life_threatening" else empty end,
          if .seriousnessdisabling == "1" then "disabling" else empty end,
          if .seriousnesscongenitalanomali == "1" then "congenital_anomaly" else empty end,
          if .seriousnessother == "1" then "other_serious" else empty end
        ] | unique;

      def reactions:
        [ .patient.reaction[]?.reactionmeddrapt | select(type == "string" and length > 0) ] | unique;

      def drugs_for_target:
        [
          .patient.drug[]?
          | (
              (((.openfda.generic_name // []) | map(ascii_downcase) | index($drug_lower)) != null)
              or ((.medicinalproduct // "") | ascii_downcase | contains($drug_lower))
            ) as $is_target
          | {
              drug_id: (if $is_target then $drug_id else null end),
              drug_name: (.medicinalproduct // (.openfda.brand_name[0]? // .openfda.generic_name[0]? // "UNKNOWN")),
              role: role_from_code
            }
        ];

      .results[]?
      | select(.safetyreportid != null)
      | {
          safetyreportid: (.safetyreportid | tostring),
          version: ((.safetyreportversion // "1") | tonumber? // 1),
          receivedate: normalize_date,
          patient_sex: normalize_sex,
          patient_age: normalize_age,
          serious: ((.serious // "0") == "1"),
          outcomes: outcomes,
          reactions: reactions,
          drugs: drugs_for_target
        }
      | select(.receivedate != null)
      | select((.reactions | length) > 0)
      | select((.drugs | map(select(.drug_id == $drug_id and .role == "suspect")) | length) > 0)
      ' "$tmp_json" | tee -a "$OUT_PATH" | wc -l
  } | tr -d ' ' )"

  collected=$((collected + appended))
  skip=$((skip + page_results))

  rm -f "$tmp_json"

  if (( page_results < limit )); then
    break
  fi

  if (( skip >= 25000 )); then
    echo "Reached openFDA skip ceiling at 25000. Stopping." >&2
    break
  fi
done

echo "Wrote ${collected} records to ${OUT_PATH}"
