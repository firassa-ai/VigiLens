#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"
FRONTEND_DIR="${ROOT_DIR}/frontend"
INIT_SQL="${BACKEND_DIR}/sql/init.sql"

POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-vigilens-dev-postgres}"
POSTGRES_VOLUME="${POSTGRES_VOLUME:-vigilens-dev-postgres-data}"
POSTGRES_PORT_WAS_SET=0
if [[ -n "${POSTGRES_PORT+x}" ]]; then
  POSTGRES_PORT_WAS_SET=1
fi
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_USER="${POSTGRES_USER:-vigilens}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-vigilens}"
POSTGRES_DB="${POSTGRES_DB:-vigilens}"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"

USE_DOCKER_POSTGRES=1
SEED_DEMO=1
FORCE_SEED=0
USE_EVERMEMOS="${USE_EVERMEMOS:-1}"

BACKEND_PID=""
FRONTEND_PID=""

print_help() {
  cat <<USAGE
Usage: scripts/run-dev.sh [options]

Options:
  --no-postgres   Do not start/check docker postgres container.
  --no-seed       Do not call /api/v1/admin/seed-demo after backend starts.
  --force-seed    Always call /api/v1/admin/seed-demo even if ingest state already has loaded data.
  --with-evermemos Force-enable EverMemOS dependency stack + API on localhost:1995.
  --no-evermemos  Disable EverMemOS startup for this run.
  --help          Show this help message.

Environment overrides:
  POSTGRES_CONTAINER, POSTGRES_VOLUME, POSTGRES_PORT,
  POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB,
  BACKEND_PORT, FRONTEND_PORT, DATABASE_URL, DEMO_MODE,
  OPENFDA_LIVE_BACKGROUND, OPENFDA_API_KEY, USE_EVERMEMOS
USAGE
}

for arg in "$@"; do
  case "${arg}" in
    --no-postgres)
      USE_DOCKER_POSTGRES=0
      ;;
    --no-seed)
      SEED_DEMO=0
      ;;
    --force-seed)
      FORCE_SEED=1
      ;;
    --with-evermemos)
      USE_EVERMEMOS=1
      ;;
    --no-evermemos)
      USE_EVERMEMOS=0
      ;;
    --help)
      print_help
      exit 0
      ;;
    *)
      echo "Unknown option: ${arg}" >&2
      print_help
      exit 1
      ;;
  esac
done

case "${USE_EVERMEMOS}" in
  1|true|TRUE|yes|YES|on|ON)
    USE_EVERMEMOS=1
    ;;
  *)
    USE_EVERMEMOS=0
    ;;
esac

require_cmd() {
  local name="$1"
  if ! command -v "${name}" >/dev/null 2>&1; then
    echo "Missing required command: ${name}" >&2
    exit 1
  fi
}

port_is_in_use() {
  local port="$1"
  (echo >/dev/tcp/127.0.0.1/"${port}") >/dev/null 2>&1
}

find_available_port() {
  local start_port="$1"
  local end_port="$2"
  local port
  for port in $(seq "${start_port}" "${end_port}"); do
    if ! port_is_in_use "${port}"; then
      echo "${port}"
      return 0
    fi
  done
  return 1
}

container_exists() {
  local name="$1"
  docker ps -a --format '{{.Names}}' | grep -qx "${name}"
}

container_running() {
  local name="$1"
  docker ps --format '{{.Names}}' | grep -qx "${name}"
}

container_host_port() {
  local name="$1"
  docker inspect \
    --format '{{range $p, $v := .HostConfig.PortBindings}}{{if eq $p "5432/tcp"}}{{(index $v 0).HostPort}}{{end}}{{end}}' \
    "${name}" 2>/dev/null || true
}

container_state() {
  local name="$1"
  docker inspect --format '{{.State.Status}}' "${name}" 2>/dev/null || true
}

host_postgres_port_ready() {
  local port="$1"
  python3 - "${port}" <<'PY'
import socket
import sys

port = int(sys.argv[1])
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(0.5)
try:
    sock.connect(("127.0.0.1", port))
except OSError:
    raise SystemExit(1)
finally:
    sock.close()
raise SystemExit(0)
PY
}

wait_for_container_postgres() {
  for _ in $(seq 1 60); do
    if docker exec "${POSTGRES_CONTAINER}" pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

wait_for_host_postgres() {
  local port="$1"
  for _ in $(seq 1 60); do
    if host_postgres_port_ready "${port}"; then
      return 0
    fi
    sleep 1
  done
  return 1
}

print_postgres_diagnostics() {
  echo "Postgres host readiness failed for localhost:${POSTGRES_PORT}." >&2
  echo "Container state: $(container_state "${POSTGRES_CONTAINER}")" >&2
  local mapping
  mapping="$(docker port "${POSTGRES_CONTAINER}" 5432/tcp 2>/dev/null || true)"
  if [[ -n "${mapping}" ]]; then
    echo "Docker port mapping: ${mapping}" >&2
  fi
  docker ps -a --filter "name=^/${POSTGRES_CONTAINER}$" >&2 || true
  docker logs --tail 40 "${POSTGRES_CONTAINER}" >&2 || true
}

wait_for_postgres_readiness() {
  echo "Waiting for Postgres to become ready..."
  if ! wait_for_container_postgres; then
    echo "Postgres did not become ready in time" >&2
    print_postgres_diagnostics
    return 1
  fi

  echo "Waiting for Postgres host port ${POSTGRES_PORT} to become reachable..."
  if wait_for_host_postgres "${POSTGRES_PORT}"; then
    return 0
  fi

  echo "Host-side Postgres port ${POSTGRES_PORT} never became reachable; recreating ${POSTGRES_CONTAINER} on the existing volume."
  docker rm -f "${POSTGRES_CONTAINER}" >/dev/null 2>&1 || true

  if port_is_in_use "${POSTGRES_PORT}"; then
    if [[ "${POSTGRES_PORT_WAS_SET}" -eq 1 ]]; then
      echo "Configured POSTGRES_PORT=${POSTGRES_PORT} is still occupied after container recreation." >&2
      print_postgres_diagnostics
      return 1
    fi
    POSTGRES_PORT=5432
    ensure_free_postgres_port
  fi

  create_postgres_container

  if ! wait_for_container_postgres; then
    echo "Recreated Postgres container did not become ready in time" >&2
    print_postgres_diagnostics
    return 1
  fi

  echo "Waiting for recreated Postgres host port ${POSTGRES_PORT} to become reachable..."
  if wait_for_host_postgres "${POSTGRES_PORT}"; then
    return 0
  fi

  print_postgres_diagnostics
  return 1
}

ensure_free_postgres_port() {
  if port_is_in_use "${POSTGRES_PORT}"; then
    if [[ "${POSTGRES_PORT_WAS_SET}" -eq 1 ]]; then
      echo "Configured POSTGRES_PORT=${POSTGRES_PORT} is already in use." >&2
      echo "Set a different POSTGRES_PORT and retry." >&2
      exit 1
    fi

    local fallback_port
    fallback_port="$(find_available_port 5433 5499 || true)"
    if [[ -z "${fallback_port}" ]]; then
      echo "Could not find a free host port for Postgres in range 5433-5499." >&2
      exit 1
    fi

    echo "Port ${POSTGRES_PORT} is in use; falling back to ${fallback_port} for Postgres."
    POSTGRES_PORT="${fallback_port}"
  fi
}

create_postgres_container() {
  echo "Creating Postgres container ${POSTGRES_CONTAINER} on host port ${POSTGRES_PORT}"
  docker run -d \
    --name "${POSTGRES_CONTAINER}" \
    -e "POSTGRES_USER=${POSTGRES_USER}" \
    -e "POSTGRES_PASSWORD=${POSTGRES_PASSWORD}" \
    -e "POSTGRES_DB=${POSTGRES_DB}" \
    -p "${POSTGRES_PORT}:5432" \
    -v "${POSTGRES_VOLUME}:/var/lib/postgresql/data" \
    -v "${INIT_SQL}:/docker-entrypoint-initdb.d/init.sql:ro" \
    postgres:16 >/dev/null
}

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM

  if [[ -n "${FRONTEND_PID}" ]] && kill -0 "${FRONTEND_PID}" >/dev/null 2>&1; then
    kill "${FRONTEND_PID}" >/dev/null 2>&1 || true
  fi

  if [[ -n "${BACKEND_PID}" ]] && kill -0 "${BACKEND_PID}" >/dev/null 2>&1; then
    kill "${BACKEND_PID}" >/dev/null 2>&1 || true
  fi

  wait >/dev/null 2>&1 || true
  exit "${exit_code}"
}
trap cleanup EXIT INT TERM

require_cmd curl
require_cmd npm
require_cmd python3
require_cmd uv

if [[ ! -f "${INIT_SQL}" ]]; then
  echo "Missing init sql file at ${INIT_SQL}" >&2
  exit 1
fi

NEEDS_DOCKER=0
if [[ "${USE_EVERMEMOS}" -eq 1 ]] || [[ "${USE_DOCKER_POSTGRES}" -eq 1 ]]; then
  NEEDS_DOCKER=1
fi

if [[ "${NEEDS_DOCKER}" -eq 1 ]]; then
  require_cmd docker

  if ! docker info >/dev/null 2>&1; then
    echo "Docker daemon is not running. Starting Docker Desktop..."
    open -a Docker
    printf "Waiting for Docker daemon"
    for _ in $(seq 1 60); do
      if docker info >/dev/null 2>&1; then
        printf "\n"
        break
      fi
      printf "."
      sleep 2
    done
    if ! docker info >/dev/null 2>&1; then
      echo "Docker daemon did not start in time. Please start Docker Desktop manually." >&2
      exit 1
    fi
  fi
fi

if [[ "${USE_EVERMEMOS}" -eq 1 ]]; then
  if [[ ! -x "${ROOT_DIR}/scripts/run-evermemos.sh" ]]; then
    echo "Missing executable script: ${ROOT_DIR}/scripts/run-evermemos.sh" >&2
    exit 1
  fi
  if curl -fsS "http://127.0.0.1:1995/health" >/dev/null 2>&1; then
    echo "EverMemOS is already healthy at http://localhost:1995"
  else
    echo "Starting EverMemOS stack on http://localhost:1995 ..."
    "${ROOT_DIR}/scripts/run-evermemos.sh" up
  fi
fi

if [[ "${USE_DOCKER_POSTGRES}" -eq 1 ]]; then
  if container_running "${POSTGRES_CONTAINER}"; then
    existing_port="$(container_host_port "${POSTGRES_CONTAINER}")"
    if [[ -n "${existing_port}" ]]; then
      POSTGRES_PORT="${existing_port}"
    fi
    echo "Postgres container ${POSTGRES_CONTAINER} is already running"
  elif container_exists "${POSTGRES_CONTAINER}"; then
    existing_port="$(container_host_port "${POSTGRES_CONTAINER}")"
    if [[ -n "${existing_port}" ]]; then
      POSTGRES_PORT="${existing_port}"
    fi

    if port_is_in_use "${POSTGRES_PORT}"; then
      if [[ "${POSTGRES_PORT_WAS_SET}" -eq 1 ]]; then
        echo "Configured POSTGRES_PORT=${POSTGRES_PORT} is in use, and existing container ${POSTGRES_CONTAINER} is bound to it." >&2
        echo "Choose another POSTGRES_PORT or stop the conflicting service." >&2
        exit 1
      fi
      echo "Existing container ${POSTGRES_CONTAINER} is bound to busy host port ${POSTGRES_PORT}; recreating on a free port."
      docker rm "${POSTGRES_CONTAINER}" >/dev/null
      POSTGRES_PORT=5432
      ensure_free_postgres_port
      create_postgres_container
    else
      echo "Starting existing Postgres container ${POSTGRES_CONTAINER}"
      if ! docker start "${POSTGRES_CONTAINER}" >/dev/null; then
        echo "Failed to start existing container. Recreating on a free port."
        docker rm "${POSTGRES_CONTAINER}" >/dev/null || true
        POSTGRES_PORT=5432
        ensure_free_postgres_port
        create_postgres_container
      fi
    fi
  else
    ensure_free_postgres_port
    create_postgres_container
  fi

  echo "Postgres host port: ${POSTGRES_PORT}"
  if ! wait_for_postgres_readiness; then
    exit 1
  fi
fi

if [[ ! -d "${BACKEND_DIR}/.venv" ]]; then
  echo "Installing backend dependencies with uv sync..."
  (cd "${BACKEND_DIR}" && uv sync)
fi

if [[ ! -d "${FRONTEND_DIR}/node_modules" ]]; then
  echo "Installing frontend dependencies with npm install..."
  (cd "${FRONTEND_DIR}" && npm install)
fi

DEFAULT_DATABASE_URL="postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:${POSTGRES_PORT}/${POSTGRES_DB}"
export DATABASE_URL="${DATABASE_URL:-${DEFAULT_DATABASE_URL}}"
export DEMO_MODE="${DEMO_MODE:-true}"
export OPENFDA_LIVE_BACKGROUND="${OPENFDA_LIVE_BACKGROUND:-true}"

DEFAULT_DEMO_DATA_DIR="${ROOT_DIR}/data/real"
if [[ ! -d "${DEFAULT_DEMO_DATA_DIR}" ]]; then
  DEFAULT_DEMO_DATA_DIR="${ROOT_DIR}/data/demo"
fi
export DEMO_DATA_DIR="${DEMO_DATA_DIR:-${DEFAULT_DEMO_DATA_DIR}}"
if [[ ! -d "${DEMO_DATA_DIR}" ]]; then
  echo "Configured DEMO_DATA_DIR does not exist: ${DEMO_DATA_DIR}" >&2
  exit 1
fi

kill_port_users() {
  local port="$1"
  local pids
  pids="$(lsof -ti :"${port}" 2>/dev/null || true)"
  if [[ -n "${pids}" ]]; then
    echo "Killing stale process(es) on port ${port}: ${pids//$'\n'/ }"
    echo "${pids}" | xargs kill -9 2>/dev/null || true
    sleep 1
  fi
}

if port_is_in_use "${BACKEND_PORT}"; then
  kill_port_users "${BACKEND_PORT}"
fi

echo "Starting backend on http://localhost:${BACKEND_PORT}"
(
  cd "${BACKEND_DIR}"
  uv run uvicorn app.main:app --host 0.0.0.0 --port "${BACKEND_PORT}"
) &
BACKEND_PID=$!

echo "Waiting for backend health endpoint..."
for _ in $(seq 1 90); do
  if curl -fsS "http://127.0.0.1:${BACKEND_PORT}/api/v1/health" >/dev/null; then
    break
  fi
  sleep 1
done

if ! curl -fsS "http://127.0.0.1:${BACKEND_PORT}/api/v1/health" >/dev/null; then
  echo "Backend did not become healthy in time" >&2
  exit 1
fi

if [[ "${SEED_DEMO}" -eq 1 ]]; then
  should_seed=1
  seed_reason="fresh boot"
  if [[ "${FORCE_SEED}" -ne 1 ]]; then
    semag_status_json="$(curl -fsS "http://127.0.0.1:${BACKEND_PORT}/api/v1/ingest/status?drug_id=semaglutide" || true)"
    minoxidil_status_json="$(curl -fsS "http://127.0.0.1:${BACKEND_PORT}/api/v1/ingest/status?drug_id=minoxidil" || true)"
    if [[ -n "${semag_status_json}" && -n "${minoxidil_status_json}" ]]; then
      read -r semag_quarters_count semag_reports_count minoxidil_quarters_count minoxidil_reports_count <<<"$(
        SEED_STATUS_SEMAG="${semag_status_json}" SEED_STATUS_MINOXIDIL="${minoxidil_status_json}" python3 - <<'PY'
import json
import os

def summarize(env_name: str) -> tuple[int, int]:
    raw = os.environ.get(env_name, "")
    try:
        payload = json.loads(raw)
    except Exception:
        return 0, 0
    quarters = payload.get("quarters_loaded") or []
    reports = payload.get("total_reports_loaded") or 0
    try:
        reports_int = int(reports)
    except Exception:
        reports_int = 0
    return len(quarters), reports_int

semag_quarters, semag_reports = summarize("SEED_STATUS_SEMAG")
minoxidil_quarters, minoxidil_reports = summarize("SEED_STATUS_MINOXIDIL")
print(f"{semag_quarters} {semag_reports} {minoxidil_quarters} {minoxidil_reports}")
PY
      )"
      if [[ "${semag_quarters_count}" -ge 4 ]] && [[ "${minoxidil_quarters_count}" -ge 24 ]]; then
        should_seed=0
        seed_reason="existing two-drug ingest state detected (semaglutide: ${semag_quarters_count} quarters/${semag_reports_count} reports, minoxidil: ${minoxidil_quarters_count} quarters/${minoxidil_reports_count} reports)"
      fi
    fi
  else
    seed_reason="forced via --force-seed"
  fi

  if [[ "${should_seed}" -eq 1 ]]; then
    echo "Seeding two-drug demo (${seed_reason})..."
    "${ROOT_DIR}/scripts/bootstrap-two-drug-demo.sh" \
      --api-base "http://127.0.0.1:${BACKEND_PORT}/api/v1" \
      --data-dir "${DEMO_DATA_DIR}" \
      >/dev/null
  else
    echo "Skipping demo seed: ${seed_reason}."
    echo "Use --force-seed to reseed and reset preload quarters."
  fi
fi

if port_is_in_use "${FRONTEND_PORT}"; then
  kill_port_users "${FRONTEND_PORT}"
fi

echo "Starting frontend on http://localhost:${FRONTEND_PORT}"
(
  cd "${FRONTEND_DIR}"
  npm run dev -- --host 0.0.0.0 --port "${FRONTEND_PORT}"
) &
FRONTEND_PID=$!

echo ""
echo "VigiLens is running:"
echo "  Frontend: http://localhost:${FRONTEND_PORT}"
echo "  Backend:  http://localhost:${BACKEND_PORT}/api/v1/health"
echo ""
echo "Press Ctrl+C to stop frontend/backend processes."

while true; do
  if ! kill -0 "${BACKEND_PID}" >/dev/null 2>&1; then
    echo "Backend process exited" >&2
    exit 1
  fi
  if ! kill -0 "${FRONTEND_PID}" >/dev/null 2>&1; then
    echo "Frontend process exited" >&2
    exit 1
  fi
  sleep 1
done
