#!/usr/bin/env bash
# Start the backend and the UI together; Ctrl+C stops both.
# Usage: ./run.sh [backend options]   (default: single Mac with a fake neighbour)
#   ./run.sh --channel 1              # a follower in the room
#   ./run.sh --channel 0 --conductor  # the conductor in the room
set -euo pipefail
cd "$(dirname "$0")"

args=("$@")
[ ${#args[@]} -eq 0 ] && args=(--channel 0 --conductor --fake-neighbour 3)

.venv/bin/python -m backend.app "${args[@]}" &
backend=$!
trap 'kill $backend 2>/dev/null' EXIT

(sleep 3 && open http://localhost:5173) &
cd frontend && npm run dev
