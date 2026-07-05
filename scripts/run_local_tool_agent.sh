#!/usr/bin/env sh
set -eu

if [ "$#" -lt 1 ]; then
  echo "Usage: $0 <server-url> [agent-name]" >&2
  exit 2
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON_BIN=${PYTHON:-python3}
AGENT_NAME=${2:-local-agent}

exec "$PYTHON_BIN" "$SCRIPT_DIR/local_tool_agent.py" --server "$1" --agent-name "$AGENT_NAME"
