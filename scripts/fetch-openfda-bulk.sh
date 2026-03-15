#!/usr/bin/env bash
set -euo pipefail

OPENFDA_URL="https://api.fda.gov/drug/event.json"
DRUG_ID="semaglutide"
START_DATE="20180101"
END_DATE="20231231"
MAX_REPORTS=20000
WINDOW_MODE="month"
OUT_PATH=""

usage() {
  cat <<USAGE
Usage: scripts/fetch-openfda-bulk.sh [options]

High-volume openFDA fetch for transformed VigiLens NDJSON rows.
Splits by time windows to stay under openFDA skip ceiling per query.

Options:
  --drug <name>          Generic drug name (default: semaglutide)
  --start <YYYYMMDD>     Start date inclusive (default: 20180101)
  --end <YYYYMMDD>       End date inclusive (default: 20231231)
  --max-reports <n>      Max transformed rows to keep after dedupe (default: 20000)
  --window <mode>        quarter|month (default: month)
  --out <path>           Output NDJSON path (default: data/real-large/<drug>.ndjson)
  --help                 Show this help

Environment:
  OPENFDA_API_KEY        Optional. Strongly recommended for larger pulls.
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
    --window)
      WINDOW_MODE="$2"
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
require_cmd mktemp

if [[ "$WINDOW_MODE" != "quarter" && "$WINDOW_MODE" != "month" ]]; then
  echo "--window must be 'quarter' or 'month'" >&2
  exit 1
fi

if [[ -z "$OUT_PATH" ]]; then
  ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  OUT_PATH="${ROOT_DIR}/data/real-large/${DRUG_ID}.ndjson"
fi

mkdir -p "$(dirname "$OUT_PATH")"
raw_tmp="$(mktemp)"
trap 'rm -f "$raw_tmp"' EXIT
: > "$raw_tmp"

DRUG_LOWER="$(printf '%s' "$DRUG_ID" | tr '[:upper:]' '[:lower:]')"
start_year=${START_DATE:0:4}
end_year=${END_DATE:0:4}

generate_windows() {
  if [[ "$WINDOW_MODE" == "quarter" ]]; then
    for (( y=start_year; y<=end_year; y++ )); do
      for q in 1 2 3 4; do
        case "$q" in
          1) ws="${y}0101"; we="${y}0331" ;;
          2) ws="${y}0401"; we="${y}0630" ;;
          3) ws="${y}0701"; we="${y}0930" ;;
          4) ws="${y}1001"; we="${y}1231" ;;
        esac
        if [[ "$we" < "$START_DATE" || "$ws" > "$END_DATE" ]]; then
          continue
        fi
        [[ "$ws" < "$START_DATE" ]] && ws="$START_DATE"
        [[ "$we" > "$END_DATE" ]] && we="$END_DATE"
        echo "$ws $we"
      done
    done
  else
    for (( y=start_year; y<=end_year; y++ )); do
      for m in $(seq -w 1 12); do
        ws="${y}${m}01"
        case "$m" in
          01|03|05|07|08|10|12) last="31" ;;
          04|06|09|11) last="30" ;;
          02)
            if (( (y % 400 == 0) || (y % 4 == 0 && y % 100 != 0) )); then
              last="29"
            else
              last="28"
            fi
            ;;
        esac
        we="${y}${m}${last}"
        if [[ "$we" < "$START_DATE" || "$ws" > "$END_DATE" ]]; then
          continue
        fi
        [[ "$ws" < "$START_DATE" ]] && ws="$START_DATE"
        [[ "$we" > "$END_DATE" ]] && we="$END_DATE"
        echo "$ws $we"
      done
    done
  fi
}

transform_page() {
  local input_json="$1"
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
    ' "$input_json"
}

collected_raw=0
window_index=0
while read -r wstart wend; do
  window_index=$((window_index + 1))
  if (( collected_raw >= MAX_REPORTS )); then
    break
  fi

  search_expr="patient.drug.openfda.generic_name:${DRUG_ID} AND receivedate:[${wstart} TO ${wend}]"
  skip=0
  echo "[$DRUG_ID] window #${window_index} ${wstart}-${wend} (collected=${collected_raw}/${MAX_REPORTS})" >&2

  while (( collected_raw < MAX_REPORTS )); do
    remaining=$((MAX_REPORTS - collected_raw))
    limit=$(( remaining > 100 ? 100 : remaining ))
    page_json="$(mktemp)"

    curl_args=(
      -sS
      --get
      --connect-timeout 10
      --max-time 45
      --retry 2
      --retry-delay 1
      --retry-all-errors
      "$OPENFDA_URL"
      --data-urlencode "search=${search_expr}"
      --data-urlencode "limit=${limit}"
      --data-urlencode "skip=${skip}"
    )

    if [[ -n "${OPENFDA_API_KEY:-}" ]]; then
      curl_args+=(--data-urlencode "api_key=${OPENFDA_API_KEY}")
    fi

    http_code="$(curl "${curl_args[@]}" -o "$page_json" -w '%{http_code}')"
    if [[ "$http_code" == "404" ]]; then
      rm -f "$page_json"
      break
    fi
    if [[ "$http_code" -ge 400 ]]; then
      rm -f "$page_json"
      echo "openFDA request failed for ${wstart}-${wend} at skip=${skip} (HTTP ${http_code})" >&2
      exit 1
    fi

    page_results="$(jq '.results | length // 0' "$page_json")"
    if [[ "$page_results" -eq 0 ]]; then
      rm -f "$page_json"
      break
    fi

    appended="$({ transform_page "$page_json" | tee -a "$raw_tmp" | wc -l; } | tr -d ' ')"
    collected_raw=$((collected_raw + appended))
    rm -f "$page_json"

    if (( page_results < limit )); then
      break
    fi

    skip=$((skip + page_results))
    if (( skip >= 25000 )); then
      echo "Window ${wstart}-${wend} hit skip ceiling; continuing with next window." >&2
      break
    fi
  done

done < <(generate_windows)

if [[ ! -s "$raw_tmp" ]]; then
  : > "$OUT_PATH"
  echo "Wrote 0 records to ${OUT_PATH}"
  exit 0
fi

jq -cs '
  sort_by(.safetyreportid, (.version // 0))
  | group_by(.safetyreportid)
  | map(last)
  | .[]
' "$raw_tmp" > "$OUT_PATH"

final_count="$(wc -l < "$OUT_PATH" | tr -d ' ')"
echo "Wrote ${final_count} deduplicated records to ${OUT_PATH}"
