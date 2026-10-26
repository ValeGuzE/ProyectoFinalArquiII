#!/bin/bash
set -e

SERVIDOR="kafka:9092"
RETENCION_MS=604800000

crear_topic() {
  nombre=$1
  particiones=$2
  /opt/kafka/bin/kafka-topics.sh --bootstrap-server "$SERVIDOR" --create --if-not-exists \
    --topic "$nombre" --partitions "$particiones" --replication-factor 1 \
    --config retention.ms=$RETENCION_MS
  echo "Topic listo: $nombre ($particiones particiones)"
}

crear_topic events.standardized 3
crear_topic events.invalid 1
crear_topic correlated.alerts 3
crear_topic external.pnc 1
crear_topic external.bomberos 1
crear_topic external.conred 1

echo "Topics existentes:"
/opt/kafka/bin/kafka-topics.sh --bootstrap-server "$SERVIDOR" --list
