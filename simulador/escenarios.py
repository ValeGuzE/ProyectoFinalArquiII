import logging
import threading
import time

import configuracion
import envio
from cargar_buscados import PLACAS_BUSCADAS
from generadores import (evento_acustico, evento_lpr, evento_panico, evento_reporte, evento_velocidad,
                         placa_aleatoria)

log = logging.getLogger("escenarios")

ESCENARIOS = configuracion.cargar()["escenarios"]
ESPERADAS = {nombre: escenario["alertaEsperada"] for nombre, escenario in ESCENARIOS.items()}


def placa_del_paso(paso, placas):
    nombre = paso.get("placa")
    if nombre is None:
        return None
    if nombre == "BUSCADA":
        return PLACAS_BUSCADAS[0]
    if nombre not in placas:
        placas[nombre] = placa_aleatoria()
    return placas[nombre]


def crear_evento(paso, escenario, placas):
    zona = paso["sector"]
    sensor = paso["sensor"]
    if sensor == "panico":
        return evento_panico(zona, paso.get("tipo"), escenario, centro=True)
    if sensor == "lpr":
        return evento_lpr(zona, placa_del_paso(paso, placas), paso.get("velocidad"), paso.get("direccion"),
                          escenario, centro=True, numero=paso.get("camara"))
    if sensor == "velocidad":
        return evento_velocidad(zona, paso.get("velocidad"), paso.get("anomalia"), escenario, centro=True)
    if sensor == "acustico":
        return evento_acustico(zona, paso.get("sonido"), paso.get("probabilidad"), escenario, centro=True)
    return evento_reporte(zona, paso.get("tipo"), paso.get("mensaje"), paso.get("origen"), escenario, centro=True)


def correr(nombre, velocidad):
    escenario = ESCENARIOS[nombre]
    placas = {}
    log.info("Inicia %s: %s", nombre, escenario.get("descripcion", ""))
    for paso in escenario["pasos"]:
        time.sleep(paso.get("esperar", 0) / velocidad)
        evento = crear_evento(paso, nombre, placas)
        respuesta = envio.enviar([evento])
        if respuesta and respuesta["rechazados"]:
            log.warning("%s: el ingestor RECHAZÓ %s: %s", nombre, evento["eventType"], respuesta["motivos"])
        else:
            log.info("%s: enviado %s (%s)", nombre, evento["eventType"], evento["location"]["zone"])
    log.info("Termina %s (alerta esperada: %s)", nombre, ESPERADAS[nombre])


def ejecutar(nombre, velocidad=1):
    nombres = list(ESCENARIOS) if nombre == "todos" else [nombre]
    for n in nombres:
        if n not in ESCENARIOS:
            raise SystemExit(f"Escenario desconocido: {n}. Opciones: {', '.join(ESCENARIOS)} o todos")
    inicio = time.time()
    hilos = [threading.Thread(target=correr, args=(n, velocidad), daemon=True) for n in nombres]
    for hilo in hilos:
        hilo.start()
    try:
        for hilo in hilos:
            hilo.join()
    except KeyboardInterrupt:
        log.info("Escenarios detenidos por el usuario antes de terminar")
    envio.imprimir_resumen(time.time() - inicio)
    print("Los falsos positivos (PANICO_NO_CONFIRMADO) aparecen cuando se cierra la ventana de")
    print("correlación. Espera ese tiempo y luego evalúa con evaluar.py")
