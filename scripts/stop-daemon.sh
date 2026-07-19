#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
RUNTIME_DIR="${HAA_RUNTIME_DIR:-${PROJECT_DIR}/data}"
PID_FILE="${RUNTIME_DIR}/haa-daemon.pid"

if [[ ! -f "${PID_FILE}" ]]; then
    echo "HAA daemon is not running (PID file not found)."
    exit 0
fi

daemon_pid="$(<"${PID_FILE}")"
if [[ ! "${daemon_pid}" =~ ^[0-9]+$ ]]; then
    echo "Invalid PID file: ${PID_FILE}" >&2
    exit 1
fi

if ! kill -0 "${daemon_pid}" 2>/dev/null; then
    rm -f -- "${PID_FILE}"
    echo "HAA daemon is not running; removed stale PID file."
    exit 0
fi

process_cwd="$(readlink -f "/proc/${daemon_pid}/cwd" 2>/dev/null || true)"
process_cmd="$({ tr '\0' ' ' <"/proc/${daemon_pid}/cmdline"; } 2>/dev/null || true)"
if [[ "${process_cwd}" != "${PROJECT_DIR}" || "${process_cmd}" != *"haa daemon"* ]]; then
    echo "Refusing to stop PID ${daemon_pid}: it does not look like this project's HAA daemon." >&2
    echo "Process directory: ${process_cwd:-unknown}" >&2
    echo "Process command: ${process_cmd:-unknown}" >&2
    exit 1
fi

echo "Stopping HAA daemon (PID ${daemon_pid})..."
kill -TERM "${daemon_pid}"

for _ in {1..30}; do
    if ! kill -0 "${daemon_pid}" 2>/dev/null; then
        rm -f -- "${PID_FILE}"
        echo "HAA daemon stopped."
        exit 0
    fi
    sleep 1
done

echo "HAA daemon did not stop within 30 seconds; sending SIGKILL." >&2
kill -KILL "${daemon_pid}"
rm -f -- "${PID_FILE}"
echo "HAA daemon stopped forcibly."
