# Monitoreo Urbano San Juan Sacatepéquez

Simulación funcional de un sistema de monitoreo perimetral urbano para la Municipalidad de San Juan Sacatepéquez: detección, procesamiento, correlación y visualización de eventos críticos sobre una arquitectura distribuida orientada a eventos.
Proyecto final de Arquitectura de Computadores II, Universidad Mariano Gálvez (2026).

Repositorio: pendiente de agregar

```
Simuladores (5 sensores, escenarios, reporte manual, JMeter)
        |  HTTP POST
        v
     NGINX :8080  ->  ingestor-1 / ingestor-2 / ingestor-3  (FastAPI: valida y estandariza)
                             |                 \
                             v                  -> Kafka events.invalid (dead-letter)
                  Kafka events.standardized
                             |
                             v
                 correlador <-> Redis (ventanas, vehículos, duplicados)
                             |  guarda en PostgreSQL
                             v
                  Kafka correlated.alerts
                             |
          +------------------+-------------------+
          v                  v                   v
     despachador         Grafana :3000       Airflow :8090
   (PNC, Bomberos,     (PostgreSQL y        (tareas periódicas)
    CONRED, aseguradora  Elasticsearch)
    y Elasticsearch)
```

## Requisitos de la laptop

| | Mínimo | Recomendado (con lo que se probó) |
|---|---|---|
| Sistema | Windows 11 o Windows 10 22H2, de 64 bits (Home o Pro) | Windows 11 Home |
| Procesador | 4 núcleos (8 hilos) con virtualización activada en la BIOS | Intel Core i7-13650HX (14 núcleos, 20 hilos) |
| Memoria RAM | 16 GB | 32 GB |
| Disco libre | 30 GB, de preferencia SSD | 50 GB o más en SSD |
| Internet | Para la instalación (descarga unos 7 GB) y para los mapas de Grafana | Igual |

El mínimo se calculó, no se probó en otra máquina. Los límites de memoria de `docker-compose.yml` suman unos 12.4 GB con el perfil `full`; el uso medido bajo carga fue de unos 4.6 GB. Con 16 GB de RAM hay que darle 12 GB a WSL2 (paso 0.5).

Puertos que deben estar libres: 3000, 5432, 6379, 8080, 8085, 8090, 9094 y 9200.

## Puesta en marcha paso a paso

Todos los comandos son de PowerShell. Sirve el que trae Windows (no hace falta PowerShell 7).

### 0. Instalar lo necesario (una sola vez por laptop)

1. **Virtualización:** abrir el Administrador de tareas, pestaña Rendimiento, CPU. Debe decir "Virtualización: Habilitado". Si dice "Deshabilitado", activarla en la BIOS (Intel VT-x o AMD-V).
2. **WSL2:** abrir PowerShell **como administrador** y ejecutar lo siguiente. Luego reiniciar la laptop.
   ```powershell
   wsl --install
   ```
3. **Docker Desktop y Git:** en PowerShell, después de reiniciar (Git solo hace falta si el proyecto se va a clonar del repositorio):
   ```powershell
   winget install -e --id Docker.DockerDesktop
   winget install -e --id Git.Git
   ```
   Abrir Docker Desktop, aceptar los términos y esperar a que diga "Engine running". Usa el motor WSL2, que viene activado por defecto. Cerrar y volver a abrir PowerShell para que reconozca los comandos nuevos.
4. **Comprobar la instalación.** Cada comando debe responder sin error, y `wsl -l -v` debe mostrar versión 2:
   ```powershell
   wsl -l -v
   docker version
   docker compose version
   docker run --rm hello-world
   git --version
   ```
5. **Memoria para WSL2:** crear el archivo `%USERPROFILE%\.wslconfig`. Para una laptop de 32 GB o más:
   ```powershell
   Set-Content "$env:USERPROFILE\.wslconfig" "[wsl2]`nmemory=20GB`nprocessors=12`nswap=4GB"
   wsl --shutdown
   ```
   - **16 GB de RAM:** usar `memory=12GB`.
   - **`processors`:** no debe pasar de los hilos que tiene la laptop. Para verlos: `(Get-CimInstance Win32_Processor).NumberOfLogicalProcessors`.
   - Después de `wsl --shutdown`, volver a abrir Docker Desktop y comprobar con `docker info --format "{{.MemTotal}} {{.NCPU}}"`.
6. **Puertos libres.** Si este comando no muestra nada, están libres:
   ```powershell
   Get-NetTCPConnection -State Listen -LocalPort 3000,5432,6379,8080,8085,8090,9094,9200 -ErrorAction SilentlyContinue
   ```

### 1. Obtener el proyecto

- **Desde el archivo comprimido:** descomprimirlo y abrir PowerShell dentro de la carpeta que contiene `docker-compose.yml`.
- **Desde el repositorio:**
  ```powershell
  git clone <dirección del repositorio> monitoreo-sjs
  cd monitoreo-sjs
  ```

Desde aquí, todos los comandos se ejecutan dentro de esa carpeta.

### 2. Crear el archivo `.env` con contraseñas aleatorias

El archivo `.env` guarda las contraseñas y la clave HMAC de las placas. No se sube a git. Este comando lo crea a partir de `.env.example` y reemplaza cada valor `CAMBIAR_...` por uno aleatorio:

```powershell
$t = Get-Content .env.example -Raw
$g = [Security.Cryptography.RandomNumberGenerator]::Create()
while ($t -match 'CAMBIAR_[A-Z]+') { $b = New-Object byte[] 16; $g.GetBytes($b); $t = $t.Replace($matches[0], -join ($b | % { '{0:x2}' -f $_ })) }
$b = New-Object byte[] 32; $g.GetBytes($b); $t = $t -replace 'PLATE_HMAC_KEY=\w+', ('PLATE_HMAC_KEY=' + -join ($b | % { '{0:x2}' -f $_ }))
[IO.File]::WriteAllText("$PWD\.env", $t)
```

Para comprobarlo: `Select-String -Path .env -Pattern PASSWORD` debe mostrar contraseñas distintas, y ninguna formada solo por ceros.

### 3. Levantar el sistema

Hay dos perfiles (usar uno a la vez):

| Perfil | Qué levanta | Cuándo usarlo |
|---|---|---|
| `core` | Kafka, Kafka UI, PostgreSQL, Redis, 3 ingestores, NGINX, correlador, despachador, aseguradora y Grafana | Desarrollo y pruebas rápidas |
| `full` | Todo lo de `core` más Elasticsearch y Airflow | Pruebas finales y demo |

```powershell
docker compose --profile full up -d --build
docker compose ps
```

La primera vez descarga y construye las imágenes (unos 7 GB): según el internet, de 10 a 30 minutos. El sistema está listo cuando `kafka`, `postgres`, `redis` y `elasticsearch` aparecen como `healthy`. Airflow tarda 1 o 2 minutos más en abrir su página.

### 4. Cargar la lista de placas robadas (una sola vez)

```powershell
docker compose run --rm simulador cargar_buscados.py
```

### 5. Comprobar que todo funciona

1. Poner el correlador en **modo demo** (ventana de 60 s y horario escolar todo el día):
   ```powershell
   $env:CORRELATION_WINDOW_SECONDS = '60'; $env:SCHOOL_HOURS = '00:00-23:59'
   docker compose up -d --no-deps correlador
   ```
2. Ejecutar los 9 escenarios a velocidad 2:
   ```powershell
   docker compose run --rm simulador simulador.py escenario todos --velocidad 2
   ```
3. Esperar unos 90 segundos, a que cierren las ventanas de los falsos positivos.
4. Evaluar. Debe terminar con "Aciertos: 9 de 9":
   ```powershell
   docker compose run --rm simulador evaluar.py --minutos 15
   ```
5. Regresar el correlador a los valores del `.env`:
   ```powershell
   Remove-Item Env:CORRELATION_WINDOW_SECONDS, Env:SCHOOL_HOURS
   docker compose up -d --no-deps correlador
   ```

Después abrir Grafana en http://localhost:3000 (usuario y contraseña en la sección siguiente), menú Dashboards, carpeta "Monitoreo SJS". Para ver datos en vivo, iniciar tráfico continuo (sección "Simulaciones").

### Al reiniciar la laptop

Abrir Docker Desktop: los servicios vuelven a arrancar solos. Si alguno no aparece en `docker compose ps`, ejecutar `docker compose --profile full up -d`.

## Direcciones y usuarios

| Servicio | URL | Usuario | Contraseña |
|---|---|---|---|
| Grafana (dashboards) | http://localhost:3000 | `admin` (`GRAFANA_ADMIN_USER`) | `GRAFANA_ADMIN_PASSWORD` del `.env` |
| Kafka UI | http://localhost:8085 | sin usuario | |
| Airflow (perfil full) | http://localhost:8090 | `admin` | `AIRFLOW_ADMIN_PASSWORD` del `.env` |
| Entrada de eventos (NGINX) | http://localhost:8080/events y /events/batch | | |
| Elasticsearch (perfil full) | http://localhost:9200 (solo desde esta máquina) | | |
| PostgreSQL | localhost:5432, base `monitoreo` (solo desde esta máquina) | `admin`, `app` o `grafana_ro` | en el `.env` |

Para ver una contraseña: `Select-String -Path .env -Pattern GRAFANA_ADMIN_PASSWORD`.

Dashboards en Grafana (carpeta "Monitoreo SJS"):
1. **Centro de Monitoreo San Juan Sacatepéquez**: mapa de calor, alertas en el mapa, tabla de alertas y contadores.
2. **Operación y SLOs**: eventos por segundo, latencia p50 y p95, inválidos, balanceo por ingestor, violaciones de SLO y envíos externos.
3. **Histórico** (perfil full): búsqueda en Elasticsearch y estadísticas de Airflow.
4. **Bandeja de instituciones**: una tabla por institución (PNC, Bomberos, CONRED y aseguradora) con las alertas que recibió cada una, las más recientes primero (tabla `dispatches`). Clic en una celda para ver la descripción completa.
5. **Despacho y falsos positivos**: a quién se envía cada tipo de alerta (regla del despachador junto a los envíos reales) y la lista de envíos, que se filtra por institución desde el encabezado de la columna. Abajo explica cómo un pánico pasa a alerta real y separa los pánicos confirmados, los falsos positivos reales (con los eventos del sector y el motivo) y los falsos positivos corregidos (marcados como falsos y confirmados después, cuando el correlador iba atrasado).
6. **Recorrido de un pánico (línea de tiempo)**: para explicar el sistema. Se elige un pánico de la lista (o se filtran solo alertas reales o solo falsos positivos) y se ve el camino que siguió: un diagrama con una caja por servicio (sensor, NGINX e ingestor, Kafka, correlador y Redis, decisión, despachador, institución), coloreada por donde pasó, con la hora y los milisegundos de cada tramo; y una línea de tiempo paso a paso que explica qué hizo cada servicio, qué otro sensor confirmó el pánico (aunque haya llegado antes) o, si fue falso positivo, qué eventos hubo en el sector y por qué no sirvieron.

## Simulaciones

Cada simulación se puede correr en primer plano (se detiene con Ctrl+C) o en segundo plano, en su propio contenedor:

```powershell
docker compose run --rm simulador simulador.py normal                      # tráfico continuo, Ctrl+C para detener
docker compose run -d --name sim-normal simulador simulador.py normal      # el mismo tráfico en segundo plano
docker logs -f sim-normal                                                  # ver sus mensajes en vivo
docker stop sim-normal; docker rm sim-normal                               # detenerlo (al detenerse imprime su resumen)
```

### Modificar escenarios y tasas: `config/simulacion.json`

Los escenarios y las tasas del tráfico normal ya no están en el código: están en `config/simulacion.json` y se edita con cualquier editor de texto. Para validarlo después de editarlo: `docker compose run --rm simulador simulador.py validar`. Se lee en cada ejecución, así que no hay que reconstruir nada. Ahí se puede:

- Cambiar el sector, los tiempos (`esperar`, en segundos desde el paso anterior) o los valores de cada paso (velocidad, probabilidad, tipo, mensaje...).
- Crear un escenario nuevo copiando uno existente y cambiándole el nombre. `alertaEsperada` es la alerta que `evaluar.py` espera (o `NINGUNA` si el escenario no debe generar alertas).
- Desactivar un escenario sin borrarlo: un guion bajo al inicio del nombre (`_ESC-ROBO-01`).
- Cambiar las tasas del tráfico normal (`tasasPorMinuto`), el porcentaje de inválidos y el tamaño del lote.

Al inicio de `config/simulacion.json` está la sección `_ayuda` (no es un archivo aparte), que explica cada campo y sus valores permitidos. Si algo está mal (sector inexistente, valor fuera de catálogo, coma de más), el simulador no envía nada y dice qué corregir:

```
config/simulacion.json tiene errores:
  - ESC-ROBO-01, paso 2: direccion 'SALIENDO' no es válido (usa ENTRADA, SALIDA)
```

## Scripts del simulador

Se ejecutan con `docker compose run --rm simulador <script> [opciones]`:

| Comando | Qué hace |
|---|---|
| `simulador.py normal [--duracion 120]` | Tráfico continuo de los 5 sensores (unos 5 eventos/s, entre 1 y 2 % inválidos a propósito). Sin `--duracion` corre hasta Ctrl+C. |
| `simulador.py pico --multiplicador 20 --duracion 60 [--hilos 16]` | Prueba de carga: multiplica las tasas. |
| `simulador.py escenario todos --velocidad 2` | Ejecuta los 9 escenarios guionados a la vez (`--velocidad` divide las esperas). |
| `simulador.py escenario ESC-ROBO-01` | Un escenario: ESC-ROBO-01, ESC-ARMADO-01, ESC-ACCIDENTE-01, ESC-INCENDIO-01, ESC-TRAMO-01, ESC-ESCOLAR-01, ESC-BUSCADO-01, ESC-FALSO-01, ESC-RUIDO-01 (o cualquiera que se agregue en `config/simulacion.json`). |
| `simulador.py validar` | Revisa `config/simulacion.json` y lista los escenarios activos. |
| `evaluar.py [--minutos 15]` | Compara las alertas obtenidas con las esperadas, solo de los escenarios que se ejecutaron en ese periodo, y guarda el resultado en `evaluation_results`. |
| `reportar.py` | Reporte ciudadano manual e interactivo (pregunta sector, tipo y mensaje). |
| `cargar_buscados.py` | Carga en Redis los hashes de las placas reportadas como robadas. |

Notas sobre los escenarios:
- Con ventana de 60 s usar `--velocidad 2` o más: ESC-ACCIDENTE-01 separa sus eventos exactamente 60 s.
- ESC-ESCOLAR-01 solo genera alerta dentro del horario escolar (`SCHOOL_HOURS`, por defecto 06:30-08:00 y 12:00-13:30). Para probarlo a cualquier hora: modo demo (paso 5 de la puesta en marcha), o `SCHOOL_HOURS=00:00-23:59` en `.env` y luego `docker compose --profile full up -d correlador`.
- Los falsos positivos (ESC-FALSO-01, ESC-RUIDO-01) aparecen al cerrar la ventana: esperar la ventana más 10 s antes de `evaluar.py`.
- Para evaluar escenarios conviene correrlos sin tráfico normal en paralelo: una alerta igual del tráfico normal en el mismo sector activa el cooldown y bloquea la del escenario.

## Pruebas de carga con JMeter

```powershell
docker run --rm --network monitoreo-sjs_default -v "${PWD}\pruebas\jmeter:/pruebas" justb4/jmeter:5.5 `
  -n -t /pruebas/carga.jmx -Jhost=nginx -Jpuerto=80 -Jhilos=16 -Jduracion=60 -Jtamano_lote=50 -l /pruebas/resultados.jtl
```

Parámetros opcionales: `hilos`, `rampa`, `duracion`, `tamano_lote` (máximo 500), `host` y `puerto`. Los eventos llevan `scenarioId = JMETER`.

## Comandos útiles

```powershell
docker compose ps                                   # estado de los servicios
docker compose logs -f correlador                   # ver alertas en vivo
docker compose logs -f despachador-es               # avisos a entidades (perfil full; en core: despachador)
docker compose stop ingestor-2                      # simular la caída de un ingestor
docker compose start ingestor-2
docker compose restart grafana                      # después de editar un dashboard JSON
docker stats                                        # CPU y memoria por contenedor
```

## Detener todo

```powershell
docker compose --profile full down       # detiene y borra contenedores; los datos quedan en los volúmenes
docker compose --profile full down -v    # además borra TODOS los datos (Kafka, PostgreSQL, Redis, Elasticsearch, Grafana, Airflow)
```

Para cambiar de perfil: `docker compose --profile core down` y luego `docker compose --profile full up -d` (o al revés).

## Estructura del proyecto

```
docker-compose.yml        servicios y perfiles
.env.example              variables de ejemplo (copiar a .env)
config/sectores.json      los 7 sectores del municipio
config/simulacion.json    escenarios guionados y tasas del tráfico (editable)
infra/                    NGINX, creación de topics de Kafka, SQL de PostgreSQL, Grafana
servicios/ingestor/       API REST de ingestión (FastAPI)
servicios/correlador/     reglas de correlación R01 a R07 y falsos positivos
servicios/despachador/    envío a PNC, Bomberos, CONRED, aseguradora y Elasticsearch
servicios/aseguradora_mock/  aseguradora simulada (REST)
simulador/                generadores de eventos, escenarios, reporte manual y evaluación
airflow/dags/             retención de datos, reporte diario y análisis de falsos positivos
pruebas/jmeter/           plan de carga
docs/entrega/             informe final del proyecto con sus anexos (Word y PDF)
```

## Privacidad

- Las placas nunca viajan ni se guardan en claro: la cámara (simulador) envía el HMAC-SHA256 con la clave `PLATE_HMAC_KEY` y una versión parcial (`P-***BCD`). El ingestor rechaza con `PLACA_EN_CLARO` cualquier evento que traiga una placa.
- Retención: eventos e inválidos 30 días, alertas 365 días (DAG `retencion_datos`).
- Grafana usa el usuario `grafana_ro`, que solo puede leer.
- Elasticsearch corre sin seguridad **solo** porque es un laboratorio en una sola máquina (puerto publicado únicamente en 127.0.0.1).
