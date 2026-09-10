#!/usr/bin/env bash
# Spares Inventory Management System - start on this machine's local network.
set -euo pipefail
cd "$(dirname "$0")"

PORT="${1:-8000}"

if [ ! -d .venv ]; then
  echo "First run - setting up. This takes a couple of minutes."
  python3 -m venv .venv
  . .venv/bin/activate
  pip install --upgrade pip --quiet
  pip install -r requirements.txt --quiet
else
  . .venv/bin/activate
fi

python manage.py init_local_env --port "$PORT"
python manage.py migrate --noinput
python manage.py collectstatic --noinput >/dev/null
python manage.py seed_defaults
python manage.py ensure_admin

exec python manage.py serve_lan --port "$PORT" --no-migrate
