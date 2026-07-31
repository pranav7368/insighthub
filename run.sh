#!/usr/bin/env bash
# Start InsightHub — backend (FastAPI :8010) + frontend (Vite :5173) together.
# Loads .env if present. Ctrl+C stops both.
set -euo pipefail
cd "$(dirname "$0")"

# load .env (KEY=VALUE lines)
if [ -f .env ]; then
  set -a; . ./.env; set +a
fi

# a secret is required with auth on; fall back to a dev value with a warning
if [ -z "${IH_SECRET_KEY:-}" ]; then
  echo "[run] IH_SECRET_KEY not set — using an insecure dev secret. Set one in .env for real use."
  export IH_SECRET_KEY="dev-only-insecure-change-me-0000000000000000"
fi

# locate the venv python (Windows vs POSIX layout)
PY=backend/.venv/Scripts/python.exe
[ -f "$PY" ] || PY=backend/.venv/bin/python
if [ ! -f "$PY" ]; then
  echo "[run] backend venv not found. First-time setup:"
  echo "      python -m venv backend/.venv && $PY -m pip install -r backend/requirements.txt"
  exit 1
fi

pids=()
cleanup() { echo; echo "[run] stopping…"; for p in "${pids[@]}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT INT TERM

echo "[run] backend  -> http://localhost:8010"
( cd backend && exec "../$PY" -m uvicorn app.main:app --port 8010 ) &
pids+=($!)

echo "[run] frontend -> http://localhost:5173"
( cd frontend && exec npm run dev ) &
pids+=($!)

echo "[run] both starting. Open http://localhost:5173  (Ctrl+C to stop)"
wait
