import json
import os

import redis

VENTANA = int(os.getenv("CORRELATION_WINDOW_SECONDS", "300"))
TTL_VEHICULO = 3600

r = redis.Redis(host=os.getenv("REDIS_HOST", "redis"), port=6379, decode_responses=True)


def leer_lote(eventos):
    lote = {"repetidos": set(), "pasos": {}, "buscadas": set(), "pasos_nuevos": {}}
    if not eventos:
        return lote
    ids = [e["eventId"] for e in eventos]
    placas = list({e["data"]["plateHash"] for e in eventos if e["eventType"] == "traffic.lpr.read"})
    tuberia = r.pipeline()
    tuberia.mget([f"evento:{event_id}" for event_id in ids])
    if placas:
        tuberia.mget([f"vehiculo:{placa}" for placa in placas])
        tuberia.smismember("placas_buscadas", placas)
    respuestas = tuberia.execute()
    lote["repetidos"] = {event_id for event_id, ya in zip(ids, respuestas[0]) if ya}
    if placas:
        lote["pasos"] = {placa: json.loads(paso) for placa, paso in zip(placas, respuestas[1]) if paso}
        lote["buscadas"] = {placa for placa, esta in zip(placas, respuestas[2]) if esta}
    return lote


def guardar_lote(ids, pasos_nuevos):
    tuberia = r.pipeline()
    for event_id in ids:
        tuberia.set(f"evento:{event_id}", 1, ex=3600)
    for placa, paso in pasos_nuevos.items():
        tuberia.set(f"vehiculo:{placa}", json.dumps(paso), ex=TTL_VEHICULO)
    tuberia.execute()


TIPOS_VENTANA = ["panico", "lpr", "velocidad", "acustico", "reporte"]
MAXIMO_POR_TIPO = 20


def es_relevante(resumen):
    if resumen["tipo"] == "velocidad":
        return resumen["d"]["anomalyType"] != "NINGUNA"
    if resumen["tipo"] == "lpr":
        return resumen["d"]["direction"] == "SALIDA"
    return True


def agregar_y_leer_ventana(resumen):
    if not es_relevante(resumen):
        return []
    clave = f"ventana:{resumen['zone']}:{resumen['tipo']}"
    tuberia = r.pipeline()
    tuberia.zadd(clave, {json.dumps(resumen): resumen["ts"]})
    tuberia.zremrangebyscore(clave, "-inf", resumen["ts"] - VENTANA)
    tuberia.expire(clave, 2 * VENTANA)
    for tipo in TIPOS_VENTANA:
        tuberia.zrevrangebyscore(f"ventana:{resumen['zone']}:{tipo}", "+inf", resumen["ts"] - VENTANA,
                                 start=0, num=MAXIMO_POR_TIPO)
    respuestas = tuberia.execute()[3:]
    return [json.loads(m) for miembros in respuestas for m in miembros]


def libres(eventos, tipo_alerta):
    if not eventos:
        return []
    usados = r.mget([f"usado:{tipo_alerta}:{e['id']}" for e in eventos])
    return [e for e, usado in zip(eventos, usados) if usado is None]


def marcar_usados(tipo_alerta, ids):
    tuberia = r.pipeline()
    for event_id in ids:
        tuberia.set(f"usado:{tipo_alerta}:{event_id}", 1, ex=2 * VENTANA)
    tuberia.execute()


def tomar_cooldown(regla, sujeto):
    return r.set(f"cooldown:{regla}:{sujeto}", 1, nx=True, ex=VENTANA) is True


def agregar_panico_pendiente(resumen):
    tuberia = r.pipeline()
    tuberia.set(f"panico:{resumen['id']}", json.dumps(resumen), ex=2 * VENTANA + 600)
    tuberia.zadd("panicos_pendientes", {resumen["id"]: resumen["ts"]})
    tuberia.execute()


def confirmar_panico(event_id):
    r.zrem("panicos_pendientes", event_id)


def panicos_vencidos(ahora):
    vencidos = []
    for event_id in r.zrangebyscore("panicos_pendientes", "-inf", ahora - VENTANA):
        if r.zrem("panicos_pendientes", event_id) == 1:
            datos = r.get(f"panico:{event_id}")
            if datos:
                vencidos.append(json.loads(datos))
    return vencidos
