#!/bin/sh
# Zero downtime reindex: copy FROM into a new index TO, then move the "orders" alias.
# Usage (from the repo root, stack running):
#   sh deploy/compose/opensearch/reindex.sh orders-v1 orders-v2 deploy/compose/opensearch/orders-mapping-v2.json
#
# The app reads and writes only through the alias, so it never notices the switch.
set -eu

FROM="$1"; TO="$2"; MAPPING="$3"
URL="${OPENSEARCH_URL:-http://localhost:9200}"
CURL="curl -fsS --max-time 300 --retry 3 --retry-delay 2"

echo "1/4 create $TO"
$CURL -X PUT "$URL/$TO" -H 'Content-Type: application/json' --data @"$MAPPING"; echo

# version_type external keeps each document's version, so the indexer's later writes
# (external_gte) still win over older data.
REINDEX="{\"conflicts\":\"proceed\",\"source\":{\"index\":\"$FROM\"},\"dest\":{\"index\":\"$TO\",\"version_type\":\"external\"}}"

echo "2/4 copy $FROM into $TO"
$CURL -X POST "$URL/_reindex?wait_for_completion=true&refresh=true" \
  -H 'Content-Type: application/json' -d "$REINDEX"; echo

echo "3/4 move the alias in 1 atomic call"
$CURL -X POST "$URL/_aliases" -H 'Content-Type: application/json' -d "{\"actions\":[
  {\"remove\":{\"index\":\"$FROM\",\"alias\":\"orders\"}},
  {\"add\":{\"index\":\"$TO\",\"alias\":\"orders\"}}]}"; echo

echo "4/4 copy again: picks up writes that reached $FROM during step 2 (newer versions only)"
$CURL -X POST "$URL/_reindex?wait_for_completion=true&refresh=true" \
  -H 'Content-Type: application/json' -d "$REINDEX"; echo

echo "alias now: $($CURL "$URL/_cat/aliases/orders")"
echo "$FROM is kept; delete it once you are happy: curl -X DELETE $URL/$FROM"
