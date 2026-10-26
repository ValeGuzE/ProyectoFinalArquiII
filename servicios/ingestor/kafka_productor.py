import json
import os

from confluent_kafka import Producer

TOPIC_VALIDOS = "events.standardized"
TOPIC_INVALIDOS = "events.invalid"
ESPERA_CONFIRMACION_S = 5

productor = Producer({
    "bootstrap.servers": os.getenv("KAFKA_BOOTSTRAP", "kafka:9092"),
    "acks": "all",
    "enable.idempotence": True,
    "linger.ms": 5,
    "compression.type": "lz4",
    "message.timeout.ms": 30000,
})


class KafkaNoDisponible(Exception):
    pass


def publicar(mensajes):
    errores = []

    def al_entregar(error, _mensaje):
        if error is not None:
            errores.append(error)

    for topic, clave, valor in mensajes:
        try:
            productor.produce(topic, key=clave, value=json.dumps(valor, ensure_ascii=False),
                              on_delivery=al_entregar)
        except BufferError:
            raise KafkaNoDisponible("cola interna del productor llena")
        productor.poll(0)

    pendientes = productor.flush(ESPERA_CONFIRMACION_S)
    if pendientes > 0 or errores:
        raise KafkaNoDisponible(f"pendientes={pendientes} errores={len(errores)}")


def kafka_responde():
    try:
        productor.list_topics(timeout=2)
        return True
    except Exception:
        return False
