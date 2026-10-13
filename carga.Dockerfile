# Imagen del servicio de carga (job de una sola vez).
FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir "psycopg[binary]==3.2.3"

COPY carga/ ./carga/
COPY sql/ ./sql/
COPY datos/tratados/ ./datos/tratados/

CMD ["python", "carga/cargar.py"]
