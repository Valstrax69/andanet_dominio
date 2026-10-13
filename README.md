# dominio — Microservicio de dominio + carga

Lógica del asistente y único servicio que lee/escribe la base. Este repo
produce **dos imágenes**: `dominio` (la API) y `carga` (el job de carga).

## Endpoints (API)
- `GET /health` → `{status, db}`
- `POST /api/chat` `{"texto": "..."}` → `{intencion, confianza, derivar, respuesta, modelo_version}`

Pide la intención al micro de IA a través del gateway, guarda la predicción en
la base y responde con una plantilla de la FAQ. Deriva a ejecutivo si el cliente
pide un humano, si la intención es anulación (DA3) o si la IA no responde.

## Base de datos
`sql/schema.sql` crea `clientes`, `faq`, `tickets` y `predicciones`.

## Carga (job de una vez)
`carga/cargar.py` aplica el esquema y carga `datos/tratados/*.csv` con
`INSERT ... ON CONFLICT DO NOTHING` (idempotente: corre dos veces sin duplicar).
Las tablas tratadas se generan en el repo `ia` (`preparar.py`) y se copian acá.

## Probar y construir
```bash
pip install -r requirements-dev.txt
pytest -q
docker build -t dominio -f Dockerfile .
docker build -t carga   -f carga.Dockerfile .
```
