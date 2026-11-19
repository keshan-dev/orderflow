#!/bin/sh
# Creates or updates 1 Debezium connector per JSON file in /connectors (PUT is idempotent).
# Every call has a timeout and a limited number of retries. Each attempt is logged.
set -eu

CONNECT_URL="${CONNECT_URL:-http://kafka-connect:8083}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-20}"
WAIT_SECONDS="${WAIT_SECONDS:-5}"

put_connector() {
  name="$1"; file="$2"; attempt=1
  while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
    code=$(curl -s -o /tmp/response.json -w '%{http_code}' --max-time 15 \
      -X PUT -H 'Content-Type: application/json' \
      --data @"$file" "$CONNECT_URL/connectors/$name/config" || echo "000")
    echo "connector=$name attempt=$attempt http=$code"
    case "$code" in
      200|201) return 0 ;;
      4*) echo "connector=$name rejected: $(cat /tmp/response.json)"; return 1 ;;
    esac
    attempt=$((attempt + 1))
    sleep "$WAIT_SECONDS"
  done
  echo "connector=$name gave up after $MAX_ATTEMPTS attempts"
  return 1
}

# An empty folder means the mount failed. Without this check the loop would run once
# with the literal pattern and the stack would start with no CDC at all.
set -- /connectors/*.json
if [ ! -f "$1" ]; then
  echo "no connector files in /connectors, is the folder mounted?"
  exit 1
fi

for file in "$@"; do
  name=$(basename "$file" .json)
  put_connector "$name" "$file"
done

sleep 3
curl -s --max-time 10 "$CONNECT_URL/connectors?expand=status" | tr -d '\n'; echo
