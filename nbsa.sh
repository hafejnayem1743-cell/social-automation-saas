#!/data/data/com.termux/files/usr/bin/bash

ROOT="$HOME/social-automation-saas"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
mkdir -p "$BACKEND/logs" "$FRONTEND"

stop_servers() {
  pkill -TERM -f '[p]ython app/main.py' 2>/dev/null || true
  pkill -TERM -f 'social-automation-saas/frontend/node_modules/.bin/vite' 2>/dev/null || true
  sleep 1
}

clean_test_data() {
  cd "$BACKEND"
  python - <<'PY'
import sqlite3
db=sqlite3.connect("social_automation.db")
c=db.cursor()

# Only remove the exact local test data created during NBSA scheduler testing.
c.execute("""
DELETE FROM scheduled_jobs
WHERE post_id IN (
  SELECT id FROM posts
  WHERE content='NBSA scheduler end-to-end test'
)
""")
jobs=c.rowcount

c.execute("""
DELETE FROM oauth_connectors
WHERE account_name='NBSA Local Webhook'
""")
connectors=c.rowcount

c.execute("""
DELETE FROM posts
WHERE content='NBSA scheduler end-to-end test'
""")
posts=c.rowcount

db.commit()
db.close()

print(f"TEST DATA CLEAN: posts={posts}, connectors={connectors}, jobs={jobs}")
PY
}

build_all() {
  cd "$BACKEND"
  python -m py_compile \
    app/main.py \
    app/publishing_engine.py \
    app/official_publishers.py \
    app/universal_connectors.py

  cd "$FRONTEND"
  npm run build >/dev/null
}

start_servers() {
  stop_servers

  cd "$BACKEND"
  nohup python app/main.py > logs/backend.log 2>&1 &
  echo $! > .nbsa-backend.pid

  cd "$FRONTEND"
  nohup npm run dev -- --host 127.0.0.1 > vite.log 2>&1 &
  echo $! > .nbsa-frontend.pid

  sleep 3
}

status() {
  echo "=== NBSA STATUS ==="

  BACKEND_HEALTH=$(curl -fsS --max-time 5 http://127.0.0.1:8000/health 2>/dev/null || true)
  if [ -n "$BACKEND_HEALTH" ]; then
    echo "BACKEND: UP"
    echo "$BACKEND_HEALTH"
  else
    echo "BACKEND: DOWN"
  fi

  if curl -fsS --max-time 5 http://127.0.0.1:5173/ >/dev/null 2>&1; then
    echo "FRONTEND: UP"
  else
    echo "FRONTEND: DOWN"
  fi

  if grep -q "NAYEM BOSS SOCIAL AUTOMATION" "$FRONTEND/index.html"; then
    echo "BRAND: OK"
  else
    echo "BRAND: CHECK"
  fi

  if grep -qiE 'access token|refresh token' "$FRONTEND/index.html"; then
    echo "MANUAL TOKEN FIELDS: FOUND"
  else
    echo "MANUAL TOKEN FIELDS: REMOVED"
  fi

  echo "--- BACKEND LOG ---"
  tail -n 12 "$BACKEND/logs/backend.log" 2>/dev/null || true

  echo "--- VITE LOG ---"
  tail -n 8 "$FRONTEND/vite.log" 2>/dev/null || true
}

case "${1:-start}" in
  start)
    clean_test_data
    build_all
    start_servers
    status
    ;;
  restart)
    build_all
    start_servers
    status
    ;;
  stop)
    stop_servers
    echo "NBSA: STOPPED"
    ;;
  status)
    status
    ;;
  clean)
    clean_test_data
    ;;
  *)
    echo "Usage: ./nbsa.sh {start|restart|stop|status|clean}"
    exit 1
    ;;
esac
