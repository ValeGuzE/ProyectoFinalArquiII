import json
import os

import estado_redis as estado
from calculos import distancia_km, en_horario_escolar, score

PROBABILIDAD_MINIMA = float(os.getenv("ACOUSTIC_MIN_PROBABILITY", "0.7"))

with open(os.getenv("SECTORES_PATH", "/config/sectores.json"), encoding="utf-8") as archivo:
    SECTORES = {s["zone"]: s for s in json.load(archivo)["sectores"]}


def buscar(eventos, condicion):
    candidatos = [e for e in eventos if condicion(e)]
    return max(candidatos, key=lambda e: e["ts"]) if candidatos else None


def alerta(tipo, severidad, regla, eventos, descripcion, cumplidas=1, total=1):
    return {"alertType": tipo, "severity": severidad, "rule": regla, "eventos": eventos,
            "description": descripcion, "score": score(eventos, cumplidas, total)}


def es_panico(e, tipo="PANICO"):
    return e["tipo"] == "panico" and e["d"]["alertType"] == tipo


def es_exceso(e):
    return e["tipo"] == "velocidad" and e["d"]["anomalyType"] in ("EXCESO_VELOCIDAD", "TRAYECTORIA_ANOMALA")


def es_radar_exceso(e):
    return e["tipo"] == "velocidad" and e["d"]["anomalyType"] == "EXCESO_VELOCIDAD"


def es_salida(e):
    return e["tipo"] == "lpr" and e["d"]["direction"] == "SALIDA"


def es_disparo(e):
    return (e["tipo"] == "acustico" and e["d"]["soundType"] == "DISPARO"
            and e["d"]["criticalProbability"] >= PROBABILIDAD_MINIMA)


def es_reporte(e, tipo):
    return e["tipo"] == "reporte" and e["d"]["reportType"] == tipo


def es_explosion(e):
    return e["tipo"] == "acustico" and e["d"]["soundType"] == "EXPLOSION"


def lpr_rapido(e):
    return e["tipo"] == "lpr" and e["d"]["estimatedSpeedKmh"] > SECTORES[e["zone"]]["limite_kmh"]


def r01_robo(nuevo, ventana):
    if not (es_panico(nuevo) or es_salida(nuevo) or es_radar_exceso(nuevo)):
        return None
    eventos = estado.libres(ventana, "ROBO_EN_CURSO")
    panico = buscar(eventos, es_panico)
    salida = buscar(eventos, lambda e: es_salida(e) and lpr_rapido(e)) or buscar(eventos, es_salida)
    if not panico or not salida:
        return None
    usados = [panico, salida]
    if not lpr_rapido(salida):
        exceso = buscar(eventos, es_radar_exceso)
        if not exceso:
            return None
        usados.append(exceso)
    if nuevo["id"] not in [e["id"] for e in usados]:
        return None
    zona = SECTORES[nuevo["zone"]]["zoneName"]
    return alerta("ROBO_EN_CURSO", "CRITICA", "R01_ROBO_EN_CURSO", usados,
                  f"Pánico + vehículo saliendo con exceso de velocidad en {zona}")


def r02_ataque_armado(nuevo, ventana):
    if not (es_disparo(nuevo) or es_panico(nuevo)):
        return None
    eventos = estado.libres(ventana, "ATAQUE_ARMADO")
    disparo = buscar(eventos, es_disparo)
    panico = buscar(eventos, es_panico)
    if not disparo or not panico or nuevo["id"] not in (disparo["id"], panico["id"]):
        return None
    zona = SECTORES[nuevo["zone"]]["zoneName"]
    return alerta("ATAQUE_ARMADO", "CRITICA", "R02_ATAQUE_ARMADO", [disparo, panico],
                  f"Disparo detectado (probabilidad {disparo['d']['criticalProbability']}) + pánico en {zona}")


def r03_accidente(nuevo, ventana):
    if not (es_reporte(nuevo, "ACCIDENTE") or es_exceso(nuevo)):
        return None
    eventos = estado.libres(ventana, "ACCIDENTE_VIAL")
    reportes = sorted([e for e in eventos if es_reporte(e, "ACCIDENTE")], key=lambda e: e["ts"], reverse=True)
    if not reportes:
        return None
    anomalia = buscar(eventos, es_exceso)
    zona = SECTORES[nuevo["zone"]]["zoneName"]
    if anomalia and nuevo["id"] in (reportes[0]["id"], anomalia["id"]):
        return alerta("ACCIDENTE_VIAL", "ALTA", "R03_ACCIDENTE_VIAL", [reportes[0], anomalia],
                      f"Reporte de accidente + {anomalia['d']['anomalyType'].lower()} en {zona}")
    if len(reportes) >= 2 and nuevo["id"] in (reportes[0]["id"], reportes[1]["id"]):
        return alerta("ACCIDENTE_VIAL", "ALTA", "R03_ACCIDENTE_VIAL", reportes[:2],
                      f"Dos reportes ciudadanos de accidente en {zona}")
    return None


def r04_incendio(nuevo, ventana):
    if not (es_panico(nuevo, "INCENDIO") or es_reporte(nuevo, "INCENDIO") or es_explosion(nuevo)):
        return None
    eventos = estado.libres(ventana, "INCENDIO_CONFIRMADO")
    panico = buscar(eventos, lambda e: es_panico(e, "INCENDIO"))
    apoyo = buscar(eventos, lambda e: es_reporte(e, "INCENDIO") or es_explosion(e))
    if not panico or not apoyo or nuevo["id"] not in (panico["id"], apoyo["id"]):
        return None
    zona = SECTORES[nuevo["zone"]]["zoneName"]
    return alerta("INCENDIO_CONFIRMADO", "CRITICA", "R04_INCENDIO_CONFIRMADO", [panico, apoyo],
                  f"Pánico de incendio confirmado por {'reporte ciudadano' if apoyo['tipo'] == 'reporte' else 'explosión'} en {zona}")


def r05_velocidad_tramo(nuevo, anterior):
    if not anterior or anterior["dev"] == nuevo["dev"] or nuevo["ts"] <= anterior["ts"]:
        return None
    km = distancia_km(anterior["lat"], anterior["lon"], nuevo["lat"], nuevo["lon"])
    kmh = km / ((nuevo["ts"] - anterior["ts"]) / 3600)
    if kmh <= 80:
        return None
    escolar = any(SECTORES[e["zone"]]["zona_escolar"] and en_horario_escolar(e["ts"]) for e in (anterior, nuevo))
    origen, destino = SECTORES[anterior["zone"]]["zoneName"], SECTORES[nuevo["zone"]]["zoneName"]
    return alerta("VELOCIDAD_ENTRE_CAMARAS", "ALTA" if escolar else "MEDIA", "R05_VELOCIDAD_ENTRE_CAMARAS",
                  [anterior, nuevo], f"Vehículo {nuevo['d']['platePartial']} de {origen} a {destino}: "
                  f"{km:.2f} km a {kmh:.0f} km/h promedio")


def r06_zona_escolar(nuevo):
    sector = SECTORES[nuevo["zone"]]
    if (nuevo["tipo"] != "velocidad" or not sector["zona_escolar"]
            or nuevo["d"]["speedKmh"] <= 30 or not en_horario_escolar(nuevo["ts"])):
        return None
    return alerta("ZONA_ESCOLAR", "MEDIA", "R06_ZONA_ESCOLAR", [nuevo],
                  f"{nuevo['d']['speedKmh']:.0f} km/h en zona escolar de {sector['zoneName']} en horario escolar")


def r07_vehiculo_reportado(nuevo, buscada):
    if nuevo["tipo"] != "lpr" or not buscada:
        return None
    return alerta("VEHICULO_REPORTADO", "ALTA", "R07_VEHICULO_REPORTADO", [nuevo],
                  f"Vehículo reportado {nuevo['d']['platePartial']} visto en {SECTORES[nuevo['zone']]['zoneName']}")


def evaluar(nuevo, ventana, paso_anterior, buscada):
    resultados = []
    for regla in (r01_robo, r02_ataque_armado, r03_accidente, r04_incendio):
        resultados.append((regla(nuevo, ventana), nuevo["zone"]))
    resultados.append((r06_zona_escolar(nuevo), nuevo["zone"]))
    if nuevo["tipo"] == "lpr":
        placa = nuevo["d"]["plateHash"]
        resultados.append((r05_velocidad_tramo(nuevo, paso_anterior), placa))
        resultados.append((r07_vehiculo_reportado(nuevo, buscada), placa))
    return [(a, sujeto) for a, sujeto in resultados if a is not None]


def falso_positivo(panico):
    zona = SECTORES[panico["zone"]]["zoneName"]
    return alerta("PANICO_NO_CONFIRMADO", "BAJA", "FP_PANICO_NO_CONFIRMADO", [panico],
                  f"Pánico en {zona} sin eventos que lo confirmen al cerrar la ventana", cumplidas=1, total=2)
