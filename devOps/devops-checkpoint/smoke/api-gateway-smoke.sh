#!/usr/bin/env sh
set -eu

: "${UNOARENA_API_URL:?UNOARENA_API_URL must be set}"

# This smoke uses the canonical client surface conceptually; replace with your real CLI binary invocation.
# Expected CLI equivalent example:
# uno-cli --api "$UNOARENA_API_URL" room list --json

TMP_JSON="$(mktemp)"
ATTEMPT=1
MAX_ATTEMPTS=2

while [ "$ATTEMPT" -le "$MAX_ATTEMPTS" ]; do
  echo "[smoke] attempt=$ATTEMPT target=$UNOARENA_API_URL"

  # Placeholder transport call representing CLI JSON output contract.
  # Replace this block with your real CLI command once available.
  if command -v curl >/dev/null 2>&1; then
    if curl -fsS "$UNOARENA_API_URL/v1/room/list" > "$TMP_JSON"; then
      break
    fi
  fi

  if [ "$ATTEMPT" -eq "$MAX_ATTEMPTS" ]; then
    echo "[smoke] failed: service unreachable or invalid response"
    exit 1
  fi

  ATTEMPT=$((ATTEMPT + 1))
done

python3 - <<'PY' "$TMP_JSON"
import json, sys
path = sys.argv[1]
with open(path, 'r', encoding='utf-8') as f:
    data = json.load(f)
if data.get("result") != "ok":
    raise SystemExit("smoke assertion failed: result != ok")
if "rooms" not in data:
    raise SystemExit("smoke assertion failed: rooms missing")
print("[smoke] passed")
PY

rm -f "$TMP_JSON"
