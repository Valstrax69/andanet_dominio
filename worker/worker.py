"""
Worker del LLM: saca un pedido de la cola, le pide el texto a NVIDIA y lo
entrega al dominio.

Dos cosas que NO hace, a proposito:

  - No decide nada. La decision (la intencion y si se deriva) ya la tomo el
    modelo en el micro de IA. El LLM solo redacta.
  - No escribe en la base. Le entrega el texto al dominio por su ruta interna,
    porque el dominio es el unico servicio que toca la base.

Si NVIDIA no responde despues de los reintentos, se entrega el estado
"degradado" con el motivo. El cliente ya tiene su respuesta: la plantilla de la
FAQ se la dio el dominio de inmediato.
"""
import json
import os
import time

import httpx

from worker import llm

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/%2F")
URL_DOMINIO = os.getenv("URL_DOMINIO", "http://dominio:8000")
COLA = "llm"
COLA_FALLIDOS = "llm.fallidos"


def log(**campos):
    print(json.dumps({"servicio": "worker", **campos}, ensure_ascii=False), flush=True)


def entregar(id_, datos, cliente=None):
    cliente = cliente or httpx
    r = cliente.put(f"{URL_DOMINIO}/interno/predicciones/{id_}/llm", json=datos, timeout=5)
    r.raise_for_status()


def estado_actual(id_, cliente=None):
    """El estado del texto de esa prediccion, o None si la prediccion ya no existe."""
    cliente = cliente or httpx
    r = cliente.get(f"{URL_DOMINIO}/interno/predicciones/{id_}/llm", timeout=5)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json().get("estado")


def procesar(pedido, redactar=llm.redactar, cliente=None):
    estado = estado_actual(pedido["id"], cliente)
    if estado is None:
        # La prediccion no existe (por ejemplo, se vacio la base). No tiene
        # sentido gastar una llamada al LLM ni devolver el mensaje a la cola,
        # donde daria vueltas para siempre.
        return "descartado"
    if estado == "listo":
        # Idempotencia: si el worker murio despues de entregar y antes de
        # confirmar, RabbitMQ reparte el mismo mensaje otra vez. No se vuelve a
        # gastar una llamada al LLM.
        return "listo"

    inicio = time.perf_counter()
    try:
        texto = redactar(pedido["instruccion"], pedido["contenido"])
    except llm.LLMNoDisponible as e:
        entregar(pedido["id"], {"estado": "degradado", "motivo": str(e)}, cliente)
        return "degradado"
    entregar(pedido["id"], {"estado": "listo", "texto": texto,
                            "latencia_ms": round((time.perf_counter() - inicio) * 1000)}, cliente)
    return "listo"


def main():
    import pika
    parametros = pika.URLParameters(RABBITMQ_URL)
    # heartbeat largo: con los reintentos una llamada puede pasar del minuto, y
    # mientras tanto el worker no atiende la conexion. Con el valor por omision
    # RabbitMQ lo daria por muerto y cerraria el canal.
    parametros.heartbeat = 600
    conexion = pika.BlockingConnection(parametros)
    canal = conexion.channel()
    canal.queue_declare(queue=COLA_FALLIDOS, durable=True)
    canal.queue_declare(queue=COLA, durable=True,
                        arguments={"x-dead-letter-exchange": "",
                                   "x-dead-letter-routing-key": COLA_FALLIDOS})
    canal.basic_qos(prefetch_count=1)   # de a un mensaje: el siguiente espera el ack

    def al_recibir(ch, metodo, _propiedades, cuerpo):
        pedido = json.loads(cuerpo)
        try:
            estado = procesar(pedido)
        except httpx.HTTPError as e:
            # El dominio no respondio: el mensaje vuelve a la cola para despues
            log(evento="llm", id=pedido.get("id"), estado="reintentar", motivo=type(e).__name__)
            time.sleep(2)
            ch.basic_nack(delivery_tag=metodo.delivery_tag, requeue=True)
            return
        log(evento="llm", id=pedido["id"], estado=estado)
        if estado in ("listo", "descartado"):
            ch.basic_ack(delivery_tag=metodo.delivery_tag)
        else:
            # requeue=False: no vuelve a la cola (seria un bucle contra una
            # clave mala), se va a llm.fallidos
            ch.basic_nack(delivery_tag=metodo.delivery_tag, requeue=False)

    canal.basic_consume(queue=COLA, on_message_callback=al_recibir)
    log(evento="inicio", modelo=llm.MODELO or "(falta NVIDIA_MODEL)", cola=COLA)
    canal.start_consuming()


if __name__ == "__main__":
    main()
