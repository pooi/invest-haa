#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
RUNTIME_DIR="${HAA_RUNTIME_DIR:-${PROJECT_DIR}/data}"
PID_FILE="${RUNTIME_DIR}/haa-daemon.pid"
LOG_FILE="${RUNTIME_DIR}/haa-daemon.log"

mkdir -p -- "${RUNTIME_DIR}"

if [[ -f "${PID_FILE}" ]]; then
    existing_pid="$(<"${PID_FILE}")"
    if [[ "${existing_pid}" =~ ^[0-9]+$ ]] && kill -0 "${existing_pid}" 2>/dev/null; then
        echo "HAA daemon is already running (PID ${existing_pid})."
        echo "Log: ${LOG_FILE}"
        exit 0
    fi
    rm -f -- "${PID_FILE}"
fi

if [[ ! -f "${PROJECT_DIR}/.env" ]]; then
    echo "Missing configuration file: ${PROJECT_DIR}/.env" >&2
    exit 1
fi

UV_BIN="${UV_BIN:-$(command -v uv || true)}"
if [[ -z "${UV_BIN}" ]]; then
    echo "uv was not found in PATH. Install uv or set UV_BIN to its absolute path." >&2
    exit 1
fi

cd -- "${PROJECT_DIR}"
nohup "${UV_BIN}" run haa daemon >>"${LOG_FILE}" 2>&1 </dev/null &
daemon_pid=$!

printf '%s\n' "${daemon_pid}" >"${PID_FILE}.tmp"
mv -- "${PID_FILE}.tmp" "${PID_FILE}"

sleep 2
if ! kill -0 "${daemon_pid}" 2>/dev/null; then
    rm -f -- "${PID_FILE}"
    echo "HAA daemon failed to start. Recent log output:" >&2
    tail -n 20 -- "${LOG_FILE}" >&2 || true
    exit 1
fi

echo "HAA daemon started (PID ${daemon_pid})."
echo "Log: ${LOG_FILE}"
