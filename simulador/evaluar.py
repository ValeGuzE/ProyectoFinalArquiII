import argparse
import os

import psycopg2

from escenarios import ESPERADAS


def main():
    parser = argparse.ArgumentParser(description="Evalúa las alertas de los escenarios")
    parser.add_argument("--minutos", type=int, default=15, help="Solo alertas de los últimos N minutos")
    args = parser.parse_args()

    conexion = psycopg2.connect(host=os.getenv("POSTGRES_HOST", "postgres"), dbname=os.getenv("POSTGRES_DB"),
                                user=os.getenv("APP_DB_USER"), password=os.getenv("APP_DB_PASSWORD"))
    cursor = conexion.cursor()
    cursor.execute(
        """SELECT scenario_id, alert_type, count(*), max(latency_ms)
           FROM alerts
           WHERE scenario_id IS NOT NULL AND created_at > now() - make_interval(mins => %s)
           GROUP BY scenario_id, alert_type""",
        (args.minutos,),
    )
    obtenidas = {}
    for escenario, tipo, cantidad, latencia in cursor.fetchall():
        obtenidas.setdefault(escenario, {})[tipo] = (cantidad, latencia)
    cursor.execute(
        """SELECT DISTINCT scenario_id FROM events
           WHERE scenario_id IS NOT NULL AND occurred_at > now() - make_interval(mins => %s)""",
        (args.minutos,),
    )
    ejecutados = {fila[0] for fila in cursor.fetchall()}

    aciertos = evaluados = 0
    print(f"\nEvaluación de escenarios (últimos {args.minutos} minutos)\n")
    print(f"{'Escenario':<20} {'Esperada':<25} {'Resultado':<14} {'Latencia':>9}  Adicionales")
    print("-" * 100)
    for escenario, esperada in ESPERADAS.items():
        if escenario not in ejecutados:
            print(f"{escenario:<20} {esperada:<25} {'no se ejecutó':<14} {'-':>9}  -")
            continue
        evaluados += 1
        reales = obtenidas.get(escenario, {})
        latencia = "-"
        if esperada == "NINGUNA":
            resultado = "ACIERTO" if not reales else "INESPERADA"
        elif esperada in reales:
            resultado = "ACIERTO"
            latencia = f"{reales[esperada][1]} ms"
        else:
            resultado = "FALTANTE"
        aciertos += resultado == "ACIERTO"
        extras = [f"{tipo} x{c}" for tipo, (c, _) in reales.items() if tipo != esperada]
        print(f"{escenario:<20} {esperada:<25} {resultado:<14} {latencia:>9}  {', '.join(extras) or '-'}")
        cursor.execute(
            "INSERT INTO evaluation_results (scenario_id, alerta_esperada, alertas_obtenidas, resultado) "
            "VALUES (%s, %s, %s, %s)",
            (escenario, esperada, ", ".join(f"{t} x{c}" for t, (c, _) in reales.items()) or None, resultado),
        )
    conexion.commit()
    print("-" * 100)
    if evaluados:
        print(f"Aciertos: {aciertos} de {evaluados} escenarios ejecutados ({100 * aciertos / evaluados:.0f} %)")
    else:
        print("Ningún escenario envió eventos en ese periodo. Ejecuta uno o amplía --minutos.")


if __name__ == "__main__":
    main()
