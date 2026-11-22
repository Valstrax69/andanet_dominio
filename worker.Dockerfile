# Imagen del worker del LLM (EP3). No publica puertos ni recibe peticiones:
# solo consume la cola "llm" y entrega el texto al dominio.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY worker/ ./worker/

USER nobody

CMD ["python", "-m", "worker.worker"]
