#!/usr/bin/env bash
# Start the usage dashboard (backend + frontend) detached from this shell.
#
#   ./usage_dashboard/start.sh          # start both
#   ./usage_dashboard/start.sh status   # is it up?
#   ./usage_dashboard/start.sh stop     # stop both
#   ./usage_dashboard/start.sh restart
#
# Logs:  usage_dashboard/backend/server.log
#        usage_dashboard/frontend/vite.log
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT=8899          # 8787 and 8000 are used by other services on this box
FRONTEND_PORT=5199
PIDS="$DIR/.pids"

port_pid() { ss -ltnp 2>/dev/null | grep -oP "(?<=:$1 )\S*.*pid=\K[0-9]+" | head -1; }
is_up()    { curl -sf -o /dev/null --max-time 3 "$1"; }

status() {
  local b f rc=0
  b=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "http://127.0.0.1:$BACKEND_PORT/api/health")
  f=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "http://127.0.0.1:$FRONTEND_PORT/")
  [ "$b" = "200" ] && echo "  backend  :$BACKEND_PORT   UP" || { echo "  backend  :$BACKEND_PORT   DOWN ($b)"; rc=1; }
  [ "$f" = "200" ] && echo "  frontend :$FRONTEND_PORT   UP" || { echo "  frontend :$FRONTEND_PORT   DOWN ($f)"; rc=1; }
  [ "$b" = "200" ] && [ "$f" = "200" ] && echo "  open -> http://127.0.0.1:$FRONTEND_PORT"
  return $rc
}

stop() {
  for p in "$BACKEND_PORT" "$FRONTEND_PORT"; do
    local pid; pid=$(port_pid "$p")
    [ -n "${pid:-}" ] && { kill "$pid" 2>/dev/null && echo "  stopped pid $pid on :$p"; }
  done
  [ -f "$PIDS" ] && rm -f "$PIDS"
  sleep 1
}

start() {
  if [ ! -x "$DIR/backend/.venv/bin/python" ]; then
    echo "backend venv missing. Run:"
    echo "  cd $DIR/backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 1
  fi
  if [ ! -d "$DIR/frontend/node_modules" ]; then
    echo "frontend deps missing. Run:  cd $DIR/frontend && npm install"
    exit 1
  fi

  if is_up "http://127.0.0.1:$BACKEND_PORT/api/health"; then
    echo "  backend already up on :$BACKEND_PORT"
  else
    ( cd "$DIR/backend" && setsid nohup .venv/bin/python -m uvicorn app.main:app \
        --port "$BACKEND_PORT" --log-level info > server.log 2>&1 < /dev/null & echo $! >> "$PIDS" )
    echo "  backend starting on :$BACKEND_PORT"
  fi

  if is_up "http://127.0.0.1:$FRONTEND_PORT/"; then
    echo "  frontend already up on :$FRONTEND_PORT"
  else
    ( cd "$DIR/frontend" && setsid nohup npx vite --port "$FRONTEND_PORT" --strictPort \
        > vite.log 2>&1 < /dev/null & echo $! >> "$PIDS" )
    echo "  frontend starting on :$FRONTEND_PORT"
  fi

  for _ in $(seq 1 45); do
    is_up "http://127.0.0.1:$BACKEND_PORT/api/health" \
      && is_up "http://127.0.0.1:$FRONTEND_PORT/" && break
    sleep 1
  done
  echo
  status
}

case "${1:-start}" in
  start)   start ;;
  stop)    stop; echo "  stopped." ;;
  restart) stop; start ;;
  status)  status ;;
  *) echo "usage: $0 [start|stop|restart|status]"; exit 2 ;;
esac
