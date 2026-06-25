#!/usr/bin/env sh
set -eu

: "${UNOARENA_API_URL:?UNOARENA_API_URL must be set}"

CLI_BIN="${UNOARENA_CLI_BIN:-devOps/devops-checkpoint/smoke/unoarena_cli.py}"
TMP_JSON="$(mktemp)"
ATTEMPT=1
MAX_ATTEMPTS=2

while [ "$ATTEMPT" -le "$MAX_ATTEMPTS" ]; do
  echo "[smoke] attempt=$ATTEMPT target=$UNOARENA_API_URL cli=$CLI_BIN"

  if python3 "$CLI_BIN" --api "$UNOARENA_API_URL" room list --json > "$TMP_JSON"; then
    break
  fi

  if [ "$ATTEMPT" -eq "$MAX_ATTEMPTS" ]; then
    echo "[smoke] failed: CLI could not reach staging gateway or returned invalid JSON"
    exit 1
  fi

  ATTEMPT=$((ATTEMPT + 1))
done

python3 - <<'PY' "$TMP_JSON"
import json
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as handle:
    data = json.load(handle)

if data.get("result") != "ok":
    raise SystemExit("smoke assertion failed: result != ok")
if data.get("rooms") != []:
    raise SystemExit("smoke assertion failed: expected empty placeholder room list")

print("[smoke] passed")
PY

rm -f "$TMP_JSON"
