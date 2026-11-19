#!/bin/sh
# Creates every OrderFlow topic. Safe to run many times (--if-not-exists).
set -eu

BOOTSTRAP="kafka:19092"
PARTITIONS=3

for domain in orders inventory payments; do
  for suffix in "" ".retry" ".dlq"; do
    topic="${domain}.events${suffix}"
    /opt/kafka/bin/kafka-topics.sh --bootstrap-server "$BOOTSTRAP" \
      --create --if-not-exists --topic "$topic" \
      --partitions "$PARTITIONS" --replication-factor 1
  done
done

# The main event topics keep every event forever, so the search index (or any other read
# model) can always be rebuilt from Kafka alone. Retry and DLQ topics keep the default.
for domain in orders inventory payments; do
  /opt/kafka/bin/kafka-configs.sh --bootstrap-server "$BOOTSTRAP" --alter     --entity-type topics --entity-name "${domain}.events" --add-config retention.ms=-1
done

echo "topics ready:"
/opt/kafka/bin/kafka-topics.sh --bootstrap-server "$BOOTSTRAP" --list
