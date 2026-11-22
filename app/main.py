"""
Microservicio de dominio - logica del asistente ANDA.

  GET  /health                  estado del servicio, de la base y de la cola
  POST /api/chat                el endpoint que usa el front
  POST /api/predict             el mismo, con el nombre que pide el enunciado
  GET  /api/respuesta/{id}      el texto que redacto el LLM, cuando ya llego
  PUT  /interno/respuesta/{id}  lo llama el worker; no se publica a internet

Flujo de una consulta:

  1. Si el cliente pide un humano, se deriva de inmediato (RNF11).
  2. Se pide la intencion al micro de IA, que en EP3 invoca el endpoint de
     SageMaker. Si no responde, se deriva (RNF4).
  3. Se decide si derivar: anulacion (DA3), confianza bajo el umbral, o
     intencion "otra". Preferimos derivar antes que responder mal (ADR-3).
  4. Se responde al cliente con la plantilla de la FAQ. Esto es sincronico y es
     lo que mide el p95.
  5. Se publica en la cola un pedido para que el LLM redacte esa misma
     respuesta en lenguaje natural. El worker lo toma, llama a NVIDIA y
     devuelve el texto por PUT /interno/respuesta/{id}.

El paso 5 es un agregado: si NVIDIA falla, o la cola no esta, el cliente ya
tiene su respuesta. Es lo que pide el enunciado cuando dice que la prediccion
tiene que seguir funcionando aunque NVIDIA falle.

Lo que se publica en la cola es el texto YA enmascarado que devolvio el micro de
IA, nunca el que escribio el cliente: ningun dato personal sale hacia NVIDIA.
"""
import os
import re

import httpx
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from app import cola
from app.db import conectar, db_viva
from app.plantillas import DERIVACION, PLANTILLAS, buscar_respuesta
from app.seguridad import LIMITE_POR_MINUTO, autenticacion_activa, requiere_clave

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://gateway:8080")
TIMEOUT_IA = float(os.getenv("TIMEOUT_IA", "12"))
INTENCIONES_QUE_DERIVAN = {"anulacion"}   # el bot no cancela servicios (DA3)
UMBRAL_CONFIANZA = float(os.getenv("UMBRAL_CONFIANZA", "0.55"))

RE_HUMANO = re.compile(r"\b(ejecutivo|persona|humano|agente|operador|alguien real)\b",
                       re.IGNORECASE)

app = FastAPI(
    title="Andesnet - asistente ANDA",
    description="API del asistente de atencion. Requiere la cabecera X-API-Key.",
    version=os.getenv("APP_VERSION", "ep3"),
)


class Mensaje(BaseModel):
    texto: str = Field(min_length=1, max_length=2000,
                       description="El mensaje del cliente")


class TextoLLM(BaseModel):
    texto_llm: str = Field(default="", max_length=4000)
    estado: str = Field(default="ok", max_length=40)


def quiere_humano(texto):
    return bool(RE_HUMANO.search(texto))


def pedir_intencion(texto):
    """Llama al micro de IA por el gateway, que reparte entre las dos replicas.

    Reintenta una vez para tolerar el corte breve cuando una replica se detiene
    (RNF4). El timeout por omision es 12 s porque en EP3 la IA puede estar
    esperando un arranque en frio de SageMaker, que se midio en unos 6 s.
    """
    for _ in range(2):
        try:
            r = httpx.post(f"{GATEWAY_URL}/api/predict", json={"texto": texto},
                           timeout=TIMEOUT_IA)
            r.raise_for_status()
            return r.json()
        except Exception:
            continue
    return None


def guardar_prediccion(pred, derivada, estado_llm):
    """Devuelve el id de la fila, o None si la base no esta disponible.

    El registro no debe tumbar la respuesta al cliente, por eso la excepcion se
    absorbe: se pierde la trazabilidad de esa consulta, no la atencion.
    """
    try:
        with conectar() as conn:
            fila = conn.execute(
                "INSERT INTO predicciones "
                "(texto_entrada, intencion, confianza, modelo_version, derivada, estado_llm) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (pred.get("entrada_enmascarada", ""), pred.get("intencion"),
                 pred.get("confianza"), pred.get("modelo_version"), derivada, estado_llm),
            ).fetchone()
            conn.commit()
            return fila[0]
    except Exception:
        return None


def pedir_texto_al_llm(id_prediccion, intencion, texto_enmascarado, articulo):
    """Publica el pedido en la cola. Devuelve el estado que queda registrado."""
    if not cola.configurada() or id_prediccion is None:
        return "no_configurado"
    try:
        cola.publicar({
            "id": id_prediccion,
            "intencion": intencion,
            "mensaje": texto_enmascarado,   # ya enmascarado por el micro de IA
            "articulo": articulo,
        })
        return "pendiente"
    except Exception:
        return "error_cola"


@app.get("/health")
def health():
    return {
        "status": "ok",
        "db": db_viva(),
        "cola": cola.estado(),
        "autenticacion": "activa" if autenticacion_activa() else "apagada",
        "limite_por_minuto": LIMITE_POR_MINUTO,
    }


@app.post("/api/chat", dependencies=[Depends(requiere_clave)])
@app.post("/api/predict", dependencies=[Depends(requiere_clave)])
def chat(m: Mensaje):
    # 1. El cliente pide un humano (RNF11)
    if quiere_humano(m.texto):
        return {"id": None, "intencion": None, "confianza": None, "derivar": True,
                "respuesta": DERIVACION, "modelo_version": None,
                "estado_llm": "no_aplica", "motor": None}

    # 2. La intencion la da el micro de IA (SageMaker en EP3)
    pred = pedir_intencion(m.texto)
    if pred is None:
        return {"id": None, "intencion": None, "confianza": None, "derivar": True,
                "respuesta": "No puedo procesar tu consulta en este momento. " + DERIVACION,
                "modelo_version": None, "estado_llm": "no_aplica", "motor": None}

    intencion = pred.get("intencion", "otra")
    confianza = pred.get("confianza") or 0.0

    # 3. Tres motivos para derivar (ADR-3: antes derivar que responder mal)
    poco_seguro = confianza < UMBRAL_CONFIANZA
    derivar = intencion in INTENCIONES_QUE_DERIVAN or poco_seguro or intencion == "otra"

    # 4. La respuesta sincronica: la plantilla de la FAQ
    if intencion in INTENCIONES_QUE_DERIVAN:
        respuesta = PLANTILLAS["anulacion"]
    elif derivar:
        respuesta = DERIVACION
    else:
        with conectar() as conn:
            respuesta = buscar_respuesta(conn, intencion)

    # 5. El LLM redacta despues, solo cuando hay algo que redactar
    id_prediccion = guardar_prediccion(pred, derivar, "pendiente")
    if derivar:
        estado_llm = "no_aplica"
    else:
        estado_llm = pedir_texto_al_llm(id_prediccion, intencion,
                                        pred.get("entrada_enmascarada", ""), respuesta)
    if id_prediccion is not None and estado_llm != "pendiente":
        _marcar_estado(id_prediccion, estado_llm)

    return {"id": id_prediccion, "intencion": intencion, "confianza": pred.get("confianza"),
            "derivar": derivar, "respuesta": respuesta,
            "modelo_version": pred.get("modelo_version"),
            "estado_llm": estado_llm, "motor": pred.get("motor")}


def _marcar_estado(id_prediccion, estado):
    try:
        with conectar() as conn:
            conn.execute("UPDATE predicciones SET estado_llm = %s WHERE id = %s",
                         (estado, id_prediccion))
            conn.commit()
    except Exception:
        pass


@app.get("/api/respuesta/{id_prediccion}", dependencies=[Depends(requiere_clave)])
def respuesta_llm(id_prediccion: int):
    """El front consulta aqui si ya llego el texto redactado por el LLM."""
    try:
        with conectar() as conn:
            fila = conn.execute(
                "SELECT intencion, respuesta_llm, estado_llm FROM predicciones WHERE id = %s",
                (id_prediccion,)).fetchone()
    except Exception:
        raise HTTPException(status_code=503, detail="La base no esta disponible")
    if fila is None:
        raise HTTPException(status_code=404, detail="No existe esa consulta")
    return {"id": id_prediccion, "intencion": fila[0],
            "respuesta_llm": fila[1], "estado_llm": fila[2]}


@app.put("/interno/respuesta/{id_prediccion}")
def guardar_texto_llm(id_prediccion: int, cuerpo: TextoLLM):
    """Lo llama el worker cuando NVIDIA ya respondio.

    No lleva clave de API porque no se publica a internet: Caddy devuelve 404
    para /interno/*, asi que solo se llega desde la red de Docker.
    """
    try:
        with conectar() as conn:
            filas = conn.execute(
                "UPDATE predicciones SET respuesta_llm = %s, estado_llm = %s WHERE id = %s",
                (cuerpo.texto_llm or None, cuerpo.estado, id_prediccion)).rowcount
            conn.commit()
    except Exception:
        raise HTTPException(status_code=503, detail="La base no esta disponible")
    if not filas:
        raise HTTPException(status_code=404, detail="No existe esa consulta")
    return {"id": id_prediccion, "estado_llm": cuerpo.estado}
