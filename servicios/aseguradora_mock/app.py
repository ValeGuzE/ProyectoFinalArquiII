import itertools
import logging

from fastapi import Body, FastAPI

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s aseguradora: %(message)s")
log = logging.getLogger("aseguradora")

app = FastAPI(title="Aseguradora mock")
numeros = itertools.count(1)


@app.post("/siniestros")
def registrar_siniestro(alerta: dict = Body(...)):
    caso = f"SIN-2026-{next(numeros):06d}"
    log.info("Siniestro %s recibido: %s en %s (alerta %s)", caso, alerta.get("description"),
             alerta.get("zoneName"), alerta.get("alertId"))
    return {"numeroCaso": caso, "estado": "RECIBIDO"}


@app.get("/health")
def salud():
    return {"estado": "ok"}
