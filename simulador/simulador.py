import argparse
import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import configuracion
import envio
import escenarios
from generadores import (elegir_sector, evento_acustico, evento_lpr, evento_panico,
                         evento_reporte, evento_velocidad, volver_invalido)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("simulador")

TRAFICO = configuracion.cargar()["trafico"]
TAMANO_LOTE = TRAFICO["tamanoLote"]
PORCENTAJE_INVALIDOS = TRAFICO["porcentajeInvalidos"] / 100
TASAS = {tipo: por_minuto / 60 for tipo, por_minuto in TRAFICO["tasasPorMinuto"].items()}
GENERADORES = {
    "lpr": evento_lpr, "velocidad": evento_velocidad, "acustico": evento_acustico,
    "panico": evento_panico, "reporte": evento_reporte,
}


def factor_hora(tipo, hora):
    if tipo in ("lpr", "velocidad") and (6 <= hora < 9 or 17 <= hora < 20):
        return 1.5
    if tipo in ("panico", "acustico") and (hora >= 19 or hora < 2):
        return 1.5
    return 1.0


def cuantos(tasa):
    entera = int(tasa)
    return entera + (1 if random.random() < tasa - entera else 0)


def eventos_de_un_segundo(multiplicador):
    hora = datetime.now().hour
    eventos = []
    for tipo, tasa in TASAS.items():
        for _ in range(cuantos(tasa * multiplicador * factor_hora(tipo, hora))):
            evento = GENERADORES[tipo](elegir_sector())
            if random.random() < PORCENTAJE_INVALIDOS:
                evento = volver_invalido(evento)
            eventos.append(evento)
    return eventos


def trafico(multiplicador, duracion, hilos):
    log.info("Tráfico con multiplicador %s durante %s s (Ctrl+C para detener)", multiplicador, duracion or "infinitos")
    inicio = time.time()
    with ThreadPoolExecutor(max_workers=hilos) as ejecutor:
        try:
            segundo = 0
            while not duracion or segundo < duracion:
                eventos = eventos_de_un_segundo(multiplicador)
                lotes = [eventos[i:i + TAMANO_LOTE] for i in range(0, len(eventos), TAMANO_LOTE)]
                for n, lote in enumerate(lotes):
                    time.sleep(max(0, inicio + segundo + n / len(lotes) - time.time()))
                    ejecutor.submit(envio.enviar, lote)
                segundo += 1
                if segundo % 10 == 0:
                    log.info("%d s, %d eventos enviados", segundo, envio.contadores["enviados"])
                time.sleep(max(0, inicio + segundo - time.time()))
        except KeyboardInterrupt:
            log.info("Detenido por el usuario")
    envio.imprimir_resumen(time.time() - inicio)


def main():
    parser = argparse.ArgumentParser(description="Simulador de sensores San Juan Sacatepéquez")
    parser.add_argument("modo", choices=["normal", "pico", "escenario", "validar"])
    parser.add_argument("nombre", nargs="?", help="Nombre del escenario o 'todos'")
    parser.add_argument("--multiplicador", type=float, default=20)
    parser.add_argument("--duracion", type=int, default=0, help="Segundos (0 = sin fin en modo normal)")
    parser.add_argument("--velocidad", type=float, default=1, help="Acelera los escenarios")
    parser.add_argument("--hilos", type=int, default=8, help="Envíos en paralelo")
    args = parser.parse_args()
    if args.velocidad <= 0 or args.multiplicador <= 0:
        parser.error("--velocidad y --multiplicador deben ser mayores que 0")

    if args.modo == "normal":
        trafico(1, args.duracion, args.hilos)
    elif args.modo == "pico":
        trafico(args.multiplicador, args.duracion or 60, args.hilos)
    elif args.modo == "validar":
        print(f"config/simulacion.json está correcto: {len(escenarios.ESCENARIOS)} escenarios activos")
        for nombre, escenario in escenarios.ESCENARIOS.items():
            print(f"  {nombre:<20} {len(escenario['pasos'])} pasos   espera {escenario['alertaEsperada']}")
    else:
        escenarios.ejecutar(args.nombre or "todos", args.velocidad)


if __name__ == "__main__":
    main()
