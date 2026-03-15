#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/docker-compose.evermemos.yml"
VENDOR_DIR="${ROOT_DIR}/vendor"
EVERMEMOS_DIR="${VENDOR_DIR}/evermemos"
PINNED_COMMIT="${EVERMEMOS_COMMIT:-1f2f083d9fd07fd6580064bbdfc7b97da39c47bb}"
WAIT_SECONDS="${EVERMEMOS_WAIT_SECONDS:-300}"
LOCAL_ENV_FILE="${ROOT_DIR}/.env.local"

print_help() {
  cat <<USAGE
Usage: scripts/run-evermemos.sh <command>

Commands:
  up        Clone/pin EverMemOS and start dependency stack + API on :1995.
  down      Stop the EverMemOS stack.
  clean     Stop stack and remove volumes.
  status    Show compose service status.
  logs      Tail logs (service optional via EVERMEMOS_LOG_SERVICE, default: evermemos).
  health    Check http://localhost:1995/health.

Environment:
  EVERMEMOS_COMMIT            Pinned commit (default: ${PINNED_COMMIT})
  EVERMEMOS_WAIT_SECONDS      Startup wait timeout (default: ${WAIT_SECONDS})
  OPENAI_API_KEY              Optional fallback for EverMemOS key wiring.
  EVERMEMOS_LLM_API_KEY       Explicit LLM key for EverMemOS.
  EVERMEMOS_VECTORIZE_API_KEY Explicit embedding key for EverMemOS.
USAGE
}

require_cmd() {
  local name="$1"
  if ! command -v "${name}" >/dev/null 2>&1; then
    echo "Missing required command: ${name}" >&2
    exit 1
  fi
}

ensure_vendor_repo() {
  mkdir -p "${VENDOR_DIR}"

  if [[ ! -d "${EVERMEMOS_DIR}/.git" ]]; then
    echo "Cloning EverMemOS into ${EVERMEMOS_DIR}"
    git clone https://github.com/EverMind-AI/EverMemOS.git "${EVERMEMOS_DIR}"
  fi

  if ! git -C "${EVERMEMOS_DIR}" rev-parse --verify "${PINNED_COMMIT}^{commit}" >/dev/null 2>&1; then
    echo "Fetching EverMemOS refs for pinned commit ${PINNED_COMMIT}"
    git -C "${EVERMEMOS_DIR}" fetch origin --tags
  fi

  git -C "${EVERMEMOS_DIR}" checkout "${PINNED_COMMIT}" >/dev/null
  echo "EverMemOS pinned at commit ${PINNED_COMMIT}"
}

patch_openai_provider_for_direct_openai() {
  local provider_file="${EVERMEMOS_DIR}/src/memory_layer/llm/openai_provider.py"
  if [[ ! -f "${provider_file}" ]]; then
    return
  fi

  python3 - "${provider_file}" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
old = """        data = {
            \"model\": self.model,
            \"messages\": [{\"role\": \"user\", \"content\": prompt}],
            \"temperature\": temperature if temperature is not None else self.temperature,
            \"provider\": openrouter_provider,
            \"response_format\": response_format,
        }
"""
new = """        data = {
            \"model\": self.model,
            \"messages\": [{\"role\": \"user\", \"content\": prompt}],
            \"temperature\": temperature if temperature is not None else self.temperature,
            \"response_format\": response_format,
        }
        if openrouter_provider is not None:
            data[\"provider\"] = openrouter_provider
"""
if old in text:
    path.write_text(text.replace(old, new), encoding="utf-8")
PY
}

write_env_file() {
  local env_file="${EVERMEMOS_DIR}/.env"

  cat >"${env_file}" <<EOF
MONGODB_HOST=evermemos-mongodb
MONGODB_PORT=27017
MONGODB_USERNAME=admin
MONGODB_PASSWORD=memsys123
MONGODB_DATABASE=memsys
MONGODB_URI_PARAMS=socketTimeoutMS=15000&authSource=admin
ES_HOSTS=http://evermemos-elasticsearch:9200
ES_USERNAME=
ES_PASSWORD=
ES_VERIFY_CERTS=false
SELF_ES_INDEX_NS=memsys
MILVUS_HOST=evermemos-milvus
MILVUS_PORT=19530
SELF_MILVUS_COLLECTION_NS=memsys
REDIS_HOST=evermemos-redis
REDIS_PORT=6379
REDIS_DB=8
REDIS_SSL=false
API_BASE_URL=http://localhost:1995
MEMSYS_HOST=0.0.0.0
MEMSYS_PORT=1995
LOG_LEVEL=${EVERMEMOS_LOG_LEVEL:-INFO}
ENV=${EVERMEMOS_ENV:-dev}
MEMORY_LANGUAGE=${EVERMEMOS_MEMORY_LANGUAGE:-en}
LLM_PROVIDER=${EVERMEMOS_LLM_PROVIDER:-openai}
LLM_MODEL=${EVERMEMOS_LLM_MODEL:-gpt-4.1-mini}
LLM_BASE_URL=${EVERMEMOS_LLM_BASE_URL:-https://api.openai.com/v1}
LLM_API_KEY=${EVERMEMOS_LLM_API_KEY:-EMPTY}
VECTORIZE_PROVIDER=${EVERMEMOS_VECTORIZE_PROVIDER:-deepinfra}
VECTORIZE_MODEL=${EVERMEMOS_VECTORIZE_MODEL:-Qwen/Qwen3-Embedding-4B}
VECTORIZE_BASE_URL=${EVERMEMOS_VECTORIZE_BASE_URL:-https://api.deepinfra.com/v1/openai}
VECTORIZE_API_KEY=${EVERMEMOS_VECTORIZE_API_KEY:-EMPTY}
VECTORIZE_TIMEOUT=${EVERMEMOS_VECTORIZE_TIMEOUT:-30}
VECTORIZE_MAX_RETRIES=${EVERMEMOS_VECTORIZE_MAX_RETRIES:-3}
VECTORIZE_BATCH_SIZE=${EVERMEMOS_VECTORIZE_BATCH_SIZE:-10}
VECTORIZE_MAX_CONCURRENT=${EVERMEMOS_VECTORIZE_MAX_CONCURRENT:-5}
VECTORIZE_ENCODING_FORMAT=${EVERMEMOS_VECTORIZE_ENCODING_FORMAT:-float}
VECTORIZE_DIMENSIONS=${EVERMEMOS_VECTORIZE_DIMENSIONS:-1024}
RERANK_PROVIDER=${EVERMEMOS_RERANK_PROVIDER:-none}
RERANK_API_KEY=${EVERMEMOS_RERANK_API_KEY:-EMPTY}
RERANK_BASE_URL=${EVERMEMOS_RERANK_BASE_URL:-}
RERANK_MODEL=${EVERMEMOS_RERANK_MODEL:-}
RERANK_TIMEOUT=${EVERMEMOS_RERANK_TIMEOUT:-30}
RERANK_MAX_RETRIES=${EVERMEMOS_RERANK_MAX_RETRIES:-3}
RERANK_BATCH_SIZE=${EVERMEMOS_RERANK_BATCH_SIZE:-10}
RERANK_MAX_CONCURRENT=${EVERMEMOS_RERANK_MAX_CONCURRENT:-5}
EOF

  echo "Wrote ${env_file}"
}

ensure_key_defaults() {
  if [[ -z "${EVERMEMOS_LLM_API_KEY:-}" && -n "${LLM_API_KEY:-}" ]]; then
    export EVERMEMOS_LLM_API_KEY="${LLM_API_KEY}"
  fi

  if [[ -z "${EVERMEMOS_VECTORIZE_API_KEY:-}" && -n "${VECTORIZE_API_KEY:-}" ]]; then
    export EVERMEMOS_VECTORIZE_API_KEY="${VECTORIZE_API_KEY}"
  fi

  if [[ -z "${EVERMEMOS_LLM_API_KEY:-}" && -n "${OPENAI_API_KEY:-}" ]]; then
    export EVERMEMOS_LLM_API_KEY="${OPENAI_API_KEY}"
  fi

  if [[ -z "${EVERMEMOS_VECTORIZE_API_KEY:-}" && -n "${OPENAI_API_KEY:-}" ]]; then
    export EVERMEMOS_VECTORIZE_API_KEY="${OPENAI_API_KEY}"
  fi

  if [[ -z "${EVERMEMOS_VECTORIZE_API_KEY:-}" && -n "${EVERMEMOS_LLM_API_KEY:-}" ]]; then
    export EVERMEMOS_VECTORIZE_API_KEY="${EVERMEMOS_LLM_API_KEY}"
  fi

  if [[ -z "${EVERMEMOS_LLM_API_KEY:-}" || -z "${EVERMEMOS_VECTORIZE_API_KEY:-}" ]]; then
    echo "Warning: EverMemOS API keys are not fully configured." >&2
    echo "Set EVERMEMOS_LLM_API_KEY and EVERMEMOS_VECTORIZE_API_KEY for full consolidation behavior." >&2
  fi
}

wait_for_health() {
  local elapsed=0
  while [[ "${elapsed}" -lt "${WAIT_SECONDS}" ]]; do
    if curl -fsS "http://127.0.0.1:1995/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done
  return 1
}

require_cmd docker
require_cmd git
require_cmd curl
require_cmd python3

if [[ ! -f "${COMPOSE_FILE}" ]]; then
  echo "Missing compose file: ${COMPOSE_FILE}" >&2
  exit 1
fi

if [[ -f "${LOCAL_ENV_FILE}" ]]; then
  # Load local non-tracked overrides (keys, provider config) for EverMemOS runtime.
  set -a
  # shellcheck disable=SC1090
  source "${LOCAL_ENV_FILE}"
  set +a
fi

COMMAND="${1:-}"

case "${COMMAND}" in
  up)
    ensure_vendor_repo
    patch_openai_provider_for_direct_openai
    ensure_key_defaults
    write_env_file
    docker compose -f "${COMPOSE_FILE}" up -d --build
    echo "Waiting for EverMemOS health endpoint..."
    if wait_for_health; then
      echo "EverMemOS is healthy at http://localhost:1995"
    else
      echo "EverMemOS did not become healthy in time. Check logs:" >&2
      echo "  docker compose -f ${COMPOSE_FILE} logs evermemos" >&2
      exit 1
    fi
    ;;
  down)
    docker compose -f "${COMPOSE_FILE}" down
    ;;
  clean)
    docker compose -f "${COMPOSE_FILE}" down -v
    ;;
  status)
    docker compose -f "${COMPOSE_FILE}" ps
    ;;
  logs)
    docker compose -f "${COMPOSE_FILE}" logs -f "${EVERMEMOS_LOG_SERVICE:-evermemos}"
    ;;
  health)
    curl -fsS "http://127.0.0.1:1995/health"
    ;;
  ""|-h|--help|help)
    print_help
    ;;
  *)
    echo "Unknown command: ${COMMAND}" >&2
    print_help
    exit 1
    ;;
esac
