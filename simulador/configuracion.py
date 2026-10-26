import json
import os
import re

from generadores import SECTORES

RUTA = os.getenv("SIMULACION_PATH", "/config/simulacion.json")

SENSORES = ["panico", "lpr", "velocidad", "acustico", "reporte"]
CAMPOS = {
    "panico": ["tipo"],
    "lpr": ["placa", "velocidad", "direccion", "camara"],
    "velocidad": ["velocidad", "anomalia"],
    "acustico": ["sonido", "probabilidad"],
    "reporte": ["tipo", "mensaje", "origen"],
}
CATALOGOS = {
    ("panico", "tipo"): ["PANICO", "EMERGENCIA_MEDICA", "INCENDIO"],
    ("lpr", "direccion"): ["ENTRADA", "SALIDA"],
    ("velocidad", "anomalia"): ["NINGUNA", "EXCESO_VELOCIDAD", "TRAYECTORIA_ANOMALA"],
    ("acustico", "sonido"): ["DISPARO", "EXPLOSION", "VIDRIO_ROTO"],
    ("reporte", "tipo"): ["ACCIDENTE", "INCENDIO", "ALTERCADO"],
    ("reporte", "origen"): ["USUARIO", "APP", "PUNTO_FISICO"],
}
ALERTAS = ["ROBO_EN_CURSO", "ATAQUE_ARMADO", "ACCIDENTE_VIAL", "INCENDIO_CONFIRMADO", "VELOCIDAD_ENTRE_CAMARAS",
           "ZONA_ESCOLAR", "VEHICULO_REPORTADO", "PANICO_NO_CONFIRMADO", "NINGUNA"]


def es_numero(valor, minimo, maximo):
    return isinstance(valor, (int, float)) and not isinstance(valor, bool) and minimo <= valor <= maximo


def errores_de_paso(donde, paso):
    if not isinstance(paso, dict):
        return [f"{donde}: cada paso debe ir entre llaves {{ }}"]
    sensor = paso.get("sensor")
    if sensor not in SENSORES:
        return [f"{donde}: sensor '{sensor}' no existe (usa {', '.join(SENSORES)})"]
    errores = []
    if paso.get("sector") not in SECTORES:
        errores.append(f"{donde}: sector '{paso.get('sector')}' no existe (usa {', '.join(SECTORES)})")
    if not es_numero(paso.get("esperar", 0), 0, 86400):
        errores.append(f"{donde}: 'esperar' debe ser un número de segundos, 0 o más")
    for campo, valor in paso.items():
        if campo in ("sensor", "sector", "esperar") or campo.startswith("_"):
            continue
        if campo not in CAMPOS[sensor]:
            errores.append(f"{donde}: el sensor {sensor} no usa el campo '{campo}' (usa {', '.join(CAMPOS[sensor])})")
        elif (sensor, campo) in CATALOGOS and valor not in CATALOGOS[(sensor, campo)]:
            errores.append(f"{donde}: {campo} '{valor}' no es válido (usa {', '.join(CATALOGOS[(sensor, campo)])})")
    if "velocidad" in paso and not es_numero(paso["velocidad"], 0, 300):
        errores.append(f"{donde}: velocidad debe ser un número entre 0 y 300 km/h")
    if "probabilidad" in paso and not es_numero(paso["probabilidad"], 0, 1):
        errores.append(f"{donde}: probabilidad debe ser un número entre 0 y 1 (ej. 0.9)")
    if "camara" in paso and not (isinstance(paso["camara"], int) and 1 <= paso["camara"] <= 999):
        errores.append(f"{donde}: camara debe ser un número entero entre 1 y 999")
    if "mensaje" in paso and not (isinstance(paso["mensaje"], str) and len(paso["mensaje"]) <= 280):
        errores.append(f"{donde}: mensaje debe ser texto de máximo 280 caracteres")
    if "placa" in paso and not (isinstance(paso["placa"], str) and paso["placa"].strip()):
        errores.append(f"{donde}: placa debe ser 'BUSCADA' o un nombre como 'carro-A'")
    return errores


def errores_de_escenario(nombre, escenario):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", nombre):
        return [f"{nombre}: el nombre solo puede tener letras, números, guion y guion bajo"]
    if not isinstance(escenario, dict):
        return [f"{nombre}: el escenario debe ir entre llaves {{ }}"]
    errores = []
    if escenario.get("alertaEsperada") not in ALERTAS:
        errores.append(f"{nombre}: alertaEsperada '{escenario.get('alertaEsperada')}' no es válida (usa {', '.join(ALERTAS)})")
    pasos = escenario.get("pasos")
    if not isinstance(pasos, list) or not pasos:
        return errores + [f"{nombre}: necesita una lista 'pasos' con al menos un paso"]
    for numero, paso in enumerate(pasos, start=1):
        errores += errores_de_paso(f"{nombre}, paso {numero}", paso)
    return errores


def errores_de_trafico(trafico):
    if not isinstance(trafico, dict):
        return ["falta la sección 'trafico'"]
    errores = []
    tasas = trafico.get("tasasPorMinuto", {})
    for sensor in SENSORES:
        if not es_numero(tasas.get(sensor), 0, 1_000_000):
            errores.append(f"trafico.tasasPorMinuto.{sensor} debe ser un número de eventos por minuto, 0 o más")
    if not es_numero(trafico.get("porcentajeInvalidos"), 0, 100):
        errores.append("trafico.porcentajeInvalidos debe ser un número entre 0 y 100")
    if not (isinstance(trafico.get("tamanoLote"), int) and 1 <= trafico["tamanoLote"] <= 500):
        errores.append("trafico.tamanoLote debe ser un número entero entre 1 y 500")
    return errores


def cargar():
    try:
        with open(RUTA, encoding="utf-8-sig") as archivo:
            config = json.load(archivo)
    except FileNotFoundError:
        raise SystemExit(f"No se encontró {RUTA}")
    except json.JSONDecodeError as error:
        raise SystemExit(f"config/simulacion.json no es JSON válido: línea {error.lineno}, columna {error.colno} "
                         f"({error.msg}). Revisa comas, comillas y llaves cerca de esa línea.")

    escenarios = config.get("escenarios")
    if not isinstance(escenarios, dict) or not escenarios:
        raise SystemExit("config/simulacion.json necesita una sección 'escenarios' con al menos uno")
    config["escenarios"] = {n: e for n, e in escenarios.items() if not n.startswith("_")}

    errores = errores_de_trafico(config.get("trafico"))
    for nombre, escenario in config["escenarios"].items():
        errores += errores_de_escenario(nombre, escenario)
    if errores:
        raise SystemExit("config/simulacion.json tiene errores:\n  - " + "\n  - ".join(errores))
    return config
