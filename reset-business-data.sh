#!/usr/bin/env sh
# Dry-run by default. Pass "confirm" as the first argument to delete data.
set -eu

cd "$(dirname "$0")"

if [ -x ".venv/bin/python" ]; then
  PYTHON=".venv/bin/python"
else
  PYTHON="python"
fi

if [ "${1:-}" = "confirm" ]; then
  echo
  echo "WARNING: This will delete inventory/module data from the configured database."
  echo "A backup will be created first by the Django command."
  echo
  "$PYTHON" manage.py reset_business_data --confirm
else
  echo
  echo "Dry run only. No data will be deleted."
  echo "To actually reset data, run: ./reset-business-data.sh confirm"
  echo
  "$PYTHON" manage.py reset_business_data --dry-run
fi
