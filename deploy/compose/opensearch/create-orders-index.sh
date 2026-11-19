#!/bin/sh
# Creates the first orders index and points the "orders" alias at it.
# Safe to run many times: does nothing if the alias already exists.
set -eu

URL="${OPENSEARCH_URL:-http://opensearch:9200}"
INDEX="orders-v1"

if curl -fsS --max-time 10 -o /dev/null "$URL/_alias/orders"; then
  echo "alias orders already exists: $(curl -fsS --max-time 10 "$URL/_cat/aliases/orders")"
  exit 0
fi

echo "creating $INDEX"
curl -fsS --max-time 30 --retry 5 --retry-delay 3 --retry-all-errors \
  -X PUT "$URL/$INDEX" -H 'Content-Type: application/json' \
  --data @/opensearch/orders-mapping.json
echo
curl -fsS --max-time 30 -X POST "$URL/_aliases" -H 'Content-Type: application/json' \
  -d "{\"actions\":[{\"add\":{\"index\":\"$INDEX\",\"alias\":\"orders\"}}]}"
echo
echo "alias: $(curl -fsS --max-time 10 "$URL/_cat/aliases/orders")"
