import os

PLACAS_BUSCADAS = ["P777BCD", "M120XYZ", "C455KLM", "P903RST", "P318GHJ",
                   "M666NPQ", "C101DFG", "P250VWX", "P614LMN", "M889TRK"]


def main():
    import redis
    from generadores import hash_placa, placa_parcial

    cliente = redis.Redis(host=os.getenv("REDIS_HOST", "redis"), port=6379)
    hashes = [hash_placa(placa) for placa in PLACAS_BUSCADAS]
    cliente.sadd("placas_buscadas", *hashes)
    for placa in PLACAS_BUSCADAS:
        print(f"Cargada placa buscada {placa_parcial(placa)}")
    print(f"Total en placas_buscadas: {cliente.scard('placas_buscadas')}")


if __name__ == "__main__":
    main()
