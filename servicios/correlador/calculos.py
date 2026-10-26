import math
import os
from datetime import datetime, time, timedelta, timezone

HORARIO_ESCOLAR = os.getenv("SCHOOL_HOURS", "06:30-08:00,12:00-13:30")
HORA_GUATEMALA = timezone(timedelta(hours=-6))


def distancia_km(lat1, lon1, lat2, lon2):
    radio_tierra = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return 2 * radio_tierra * math.asin(math.sqrt(a))


def en_horario_escolar(ts):
    hora = datetime.fromtimestamp(ts, HORA_GUATEMALA).time()
    for rango in HORARIO_ESCOLAR.split(","):
        inicio, fin = rango.strip().split("-")
        if time.fromisoformat(inicio) <= hora <= time.fromisoformat(fin):
            return True
    return False


def confianza(e):
    if e["tipo"] == "acustico":
        return e["d"]["criticalProbability"]
    if e["tipo"] == "panico":
        return 0.9 if e["d"]["origin"] == "BOTON_FIJO" else 0.8
    if e["tipo"] == "reporte":
        return 0.8 if (e["d"].get("accuracyMeters") or 999) <= 50 else 0.7
    return 0.95


def score(eventos, cumplidas=1, total=1):
    promedio = sum(confianza(e) for e in eventos) / len(eventos)
    return round(cumplidas / total * promedio, 2)
