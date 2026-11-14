#!/usr/bin/env bash
# Start the backend and the UI together; Ctrl+C stops both.
# Usage: ./run.sh [backend options]   (default: single Mac with a fake neighbour)
#   ./run.sh --channel 1              # a follower in the room
#   ./run.sh --channel 0              # a Mac in the room (any Mac can press Start)
set -euo pipefail
cd "$(dirname "$0")"

# Stop any backend or UI left over from a previous run, so stale code never answers.
pkill -f 'backend\.app' 2>/dev/null || true
for port in 8000 5173; do kill $(lsof -ti tcp:$port) 2>/dev/null || true; done
sleep 1

args=("$@")
[ ${#args[@]} -eq 0 ] && args=(--channel 0 --fake-neighbour 3)

.venv/bin/python -m backend.app "${args[@]}" &
backend=$!
trap 'kill $backend 2>/dev/null' EXIT

(sleep 3 && open http://localhost:5173) &
cd frontend && npm run dev
