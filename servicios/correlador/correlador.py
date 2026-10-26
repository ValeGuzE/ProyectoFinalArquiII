import json
import logging
import os
import signal
import time
import uuid
from datetime import datetime

from confluent_kafka import Consumer, Producer

import base_datos as db
import estado_redis as estado
import reglas

SLO_LATENCIA_MS = int(os.getenv("SLO_LATENCIA_MS", "2000"))
KAFKA = os.getenv("KAFKA_BOOTSTRAP", "kafka:9092")
TIPOS = {"security.panic_button.pressed": "panico", "traffic.lpr.read": "lpr", "traffic.speed.reading": "velocidad",
         "environment.acoustic.detected": "acustico", "citizen.report.created": "reporte"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s correlador: %(message)s")
log = logging.getLogger("correlador")

consumidor = Consumer({"bootstrap.servers": KAFKA, "group.id": "correlador",
                       "enable.auto.commit": False, "auto.offset.reset": "earliest",
                       "session.timeout.ms": 10000})
productor = Producer({"bootstrap.servers": KAFKA, "acks": "all", "enable.idempotence": True, "linger.ms": 5})


def segundos(fecha_iso):
    return datetime.fromisoformat(fecha_iso).timestamp()


def ahora_iso():
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def resumir(e):
    return {"id": e["eventId"], "tipo": TIPOS[e["eventType"]], "ts": segundos(e["timestamp"]),
            "emit": segundos(e["emittedAt"]), "zone": e["location"]["zone"], "lat": e["location"]["latitude"],
            "lon": e["location"]["longitude"], "dev": e["device"]["deviceId"], "esc": e.get("scenarioId"),
            "d": e["data"]}


def publicar_alerta(a, ultimo_emit, status="NUEVA", medir_slo=True):
    eventos = a["eventos"]
    escenarios = {e["esc"] for e in eventos}
    ultimo = max(eventos, key=lambda e: e["ts"])
    creada = time.time()
    alerta = {
        "alertId": str(uuid.uuid4()), "alertType": a["alertType"], "severity": a["severity"], "status": status,
        "zone": ultimo["zone"], "zoneName": reglas.SECTORES[ultimo["zone"]]["zoneName"],
        "latitude": ultimo["lat"], "longitude": ultimo["lon"], "score": a["score"], "rule": a["rule"],
        "description": a["description"], "sourceEventIds": [e["id"] for e in eventos],
        "scenarioId": escenarios.pop() if len(escenarios) == 1 else None,
        "createdAt": ahora_iso(),
        "latencyMs": int((creada - ultimo_emit) * 1000),
    }
    db.guardar_alerta(alerta)
    productor.produce("correlated.alerts", key=alerta["zone"], value=json.dumps(alerta, ensure_ascii=False))
    log.info("Alerta %s generada en %s (latencia %d ms)", alerta["alertType"], alerta["zoneName"], alerta["latencyMs"])
    if medir_slo and alerta["latencyMs"] > SLO_LATENCIA_MS:
        log.warning("SLO incumplido: alerta %s tardó %d ms (umbral %d ms)",
                    alerta["alertId"], alerta["latencyMs"], SLO_LATENCIA_MS)
        db.guardar_violacion_slo(alerta["alertId"], alerta["latencyMs"], SLO_LATENCIA_MS)


def procesar(evento, lote):
    db.guardar_evento(evento)
    nuevo = resumir(evento)
    placa = nuevo["d"]["plateHash"] if nuevo["tipo"] == "lpr" else None
    paso_anterior = lote["pasos"].get(placa)
    ventana = estado.agregar_y_leer_ventana(nuevo)
    if nuevo["tipo"] == "panico":
        estado.agregar_panico_pendiente(nuevo)

    for alerta, sujeto in reglas.evaluar(nuevo, ventana, paso_anterior, placa in lote["buscadas"]):
        if not estado.tomar_cooldown(alerta["rule"], sujeto):
            continue
        ids = [e["id"] for e in alerta["eventos"]]
        estado.marcar_usados(alerta["alertType"], ids)
        for e in alerta["eventos"]:
            if e["tipo"] == "panico":
                estado.confirmar_panico(e["id"])
        publicar_alerta(alerta, nuevo["emit"])

    if placa and (not paso_anterior or nuevo["ts"] > paso_anterior["ts"]):
        lote["pasos"][placa] = nuevo
        lote["pasos_nuevos"][placa] = nuevo


def revisar_panicos():
    for panico in estado.panicos_vencidos(time.time()):
        publicar_alerta(reglas.falso_positivo(panico), panico["ts"] + estado.VENTANA,
                        status="FALSO_POSITIVO_PROBABLE", medir_slo=False)


def detener(_senal, _marco):
    global corriendo
    corriendo = False


corriendo = True


def main():
    signal.signal(signal.SIGTERM, detener)
    consumidor.subscribe(["events.standardized"])
    log.info("Correlador iniciado (ventana %d s, SLO %d ms)", estado.VENTANA, SLO_LATENCIA_MS)
    ultima_revision = time.time()
    procesados = 0
    while corriendo:
        primero = consumidor.poll(timeout=0.2)
        mensajes = [primero] + consumidor.consume(num_messages=499, timeout=0) if primero else []
        eventos = []
        for mensaje in mensajes:
            if mensaje.error():
                log.warning("Error de Kafka: %s", mensaje.error())
                continue
            eventos.append(json.loads(mensaje.value()))
        lote = estado.leer_lote(eventos)
        ids_lote = []
        for evento in eventos:
            if evento["eventId"] in lote["repetidos"]:
                continue
            lote["repetidos"].add(evento["eventId"])
            procesar(evento, lote)
            ids_lote.append(evento["eventId"])

        if time.time() - ultima_revision >= 10:
            revisar_panicos()
            ultima_revision = time.time()
            log.info("Eventos procesados en los últimos 10 s: %d", procesados)
            procesados = 0

        db.confirmar()
        productor.flush(10)
        if ids_lote:
            estado.guardar_lote(ids_lote, lote["pasos_nuevos"])
            procesados += len(ids_lote)
        if mensajes:
            consumidor.commit(asynchronous=False)

    consumidor.close()
    log.info("Correlador detenido ordenadamente")


if __name__ == "__main__":
    main()
