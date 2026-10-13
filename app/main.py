"""
Microservicio de dominio - logica del asistente ANDA.

  GET  /health    -> estado del servicio y de la base
  POST /api/chat  -> {"texto": "..."} -> intencion, respuesta, derivar

Flujo: pide la intencion al micro de IA a traves del gateway, guarda la
prediccion en la base y responde con una plantilla de la FAQ. Si el cliente
pide un humano, si la intencion es anulacion (el bot no cancela, DA3) o si la
IA no responde, deriva a un ejecutivo (RNF4, RNF8, RNF11).
"""
import os
import re

import httpx
from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.db import conectar, db_viva
from app.plantillas import buscar_respuesta, DERIVACION, PLANTILLAS

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://gateway:8080")
TIMEOUT_IA = float(os.getenv("TIMEOUT_IA", "3"))
INTENCIONES_QUE_DERIVAN = {"anulacion"}   # el bot no cancela servicios (DA3)

RE_HUMANO = re.compile(r"\b(ejecutivo|persona|humano|agente|operador|alguien real)\b", re.IGNORECASE)

app = FastAPI(title="Andesnet dominio - asistente ANDA")


class Mensaje(BaseModel):
    texto: str = Field(min_length=1, max_length=2000)


def quiere_humano(texto):
    return bool(RE_HUMANO.search(texto))


def pedir_intencion(texto):
    """Llama al micro de IA a traves del gateway. Reintenta una vez para
    tolerar el corte breve cuando se detiene una replica (RNF4)."""
    for _ in range(2):
        try:
            r = httpx.post(f"{GATEWAY_URL}/api/predict", json={"texto": texto}, timeout=TIMEOUT_IA)
            r.raise_for_status()
            return r.json()
        except Exception:
            continue
    return None


def guardar_prediccion(pred, derivada):
    try:
        with conectar() as conn:
            conn.execute(
                "INSERT INTO predicciones (texto_entrada, intencion, confianza, modelo_version, derivada) "
                "VALUES (%s, %s, %s, %s, %s)",
                (pred.get("entrada_enmascarada", ""), pred.get("intencion"),
                 pred.get("confianza"), pred.get("modelo_version"), derivada),
            )
            conn.commit()
    except Exception:
        pass  # el registro no debe tumbar la respuesta al cliente


@app.get("/health")
def health():
    return {"status": "ok", "db": db_viva()}


@app.post("/api/chat")
def chat(m: Mensaje):
    # 1. El cliente pide un humano: se deriva de inmediato (RNF11)
    if quiere_humano(m.texto):
        return {"intencion": None, "confianza": None, "derivar": True,
                "respuesta": DERIVACION, "modelo_version": None}

    # 2. Se pide la intencion al micro de IA (via gateway, que balancea las replicas)
    pred = pedir_intencion(m.texto)
    if pred is None:
        return {"intencion": None, "confianza": None, "derivar": True,
                "respuesta": "No puedo procesar tu consulta en este momento. " + DERIVACION,
                "modelo_version": None}

    intencion = pred.get("intencion", "otra")
    derivar = intencion in INTENCIONES_QUE_DERIVAN
    guardar_prediccion(pred, derivar)

    if derivar:
        respuesta = PLANTILLAS["anulacion"]
    else:
        with conectar() as conn:
            respuesta = buscar_respuesta(conn, intencion)

    return {"intencion": intencion, "confianza": pred.get("confianza"),
            "derivar": derivar, "respuesta": respuesta,
            "modelo_version": pred.get("modelo_version")}
