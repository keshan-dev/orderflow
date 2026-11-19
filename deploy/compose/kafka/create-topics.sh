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

echo "topics ready:"
/opt/kafka/bin/kafka-topics.sh --bootstrap-server "$BOOTSTRAP" --list
