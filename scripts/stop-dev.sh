#!/usr/bin/env bash
set -euo pipefail

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-vigilens-dev-postgres}"

STOP_POSTGRES=0
for arg in "$@"; do
  case "${arg}" in
    --postgres)
      STOP_POSTGRES=1
      ;;
    --help)
      cat <<USAGE
Usage: scripts/stop-dev.sh [options]

Kills backend and frontend dev processes by port, and optionally stops the Postgres container.

Options:
  --postgres   Also stop the Postgres Docker container.
  --help       Show this help message.

Environment overrides:
  BACKEND_PORT  (default 8000)
  FRONTEND_PORT (default 3000)
  POSTGRES_CONTAINER (default vigilens-dev-postgres)
USAGE
      exit 0
      ;;
    *)
      echo "Unknown option: ${arg}" >&2
      exit 1
      ;;
  esac
done

kill_port() {
  local port="$1"
  local label="$2"
  local pids
  pids="$(lsof -ti :"${port}" 2>/dev/null || true)"
  if [[ -n "${pids}" ]]; then
    echo "Stopping ${label} (port ${port}): PIDs ${pids//$'\n'/ }"
    echo "${pids}" | xargs kill -9 2>/dev/null || true
  else
    echo "No ${label} process found on port ${port}"
  fi
}

kill_port "${BACKEND_PORT}" "backend"
kill_port "${FRONTEND_PORT}" "frontend"

if [[ "${STOP_POSTGRES}" -eq 1 ]]; then
  if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' | grep -qx "${POSTGRES_CONTAINER}"; then
    echo "Stopping Postgres container ${POSTGRES_CONTAINER}"
    docker stop "${POSTGRES_CONTAINER}" >/dev/null
  else
    echo "Postgres container ${POSTGRES_CONTAINER} is not running"
  fi
fi

echo "Done."
