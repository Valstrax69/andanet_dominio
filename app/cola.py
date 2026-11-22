"""
Publica en RabbitMQ los pedidos de texto para el LLM. El worker los consume.

Sin RABBITMQ_URL (que es el caso de EP2) no hay cola y la prediccion queda con
estado_llm = "no_configurado". La respuesta al cliente no cambia: la plantilla
de la FAQ se entrega igual, y el texto del LLM es un agregado posterior.

La declaracion de la cola tiene que ser IDENTICA a la del worker. Si no
coinciden, RabbitMQ rechaza la segunda con PRECONDITION_FAILED.

Los mensajes que fallan repetidamente caen a llm.fallidos (dead letter), asi no
se pierden ni bloquean la cola principal.
"""
import json
import os

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "")
COLA = "llm"
COLA_FALLIDOS = "llm.fallidos"


def configurada():
    return bool(RABBITMQ_URL)


def _conectar():
    import pika
    p = pika.URLParameters(RABBITMQ_URL)
    p.connection_attempts = 1
    p.socket_timeout = 2
    p.blocked_connection_timeout = 5
    return pika.BlockingConnection(p)


def _declarar(canal):
    canal.queue_declare(queue=COLA_FALLIDOS, durable=True)
    canal.queue_declare(queue=COLA, durable=True,
                        arguments={"x-dead-letter-exchange": "",
                                   "x-dead-letter-routing-key": COLA_FALLIDOS})


def publicar(pedido):
    import pika
    conexion = _conectar()
    try:
        canal = conexion.channel()
        _declarar(canal)
        canal.basic_publish(exchange="", routing_key=COLA,
                            body=json.dumps(pedido, ensure_ascii=False),
                            properties=pika.BasicProperties(delivery_mode=2))  # persistente
    finally:
        conexion.close()


def estado():
    if not configurada():
        return {"estado": "no_configurada"}
    try:
        conexion = _conectar()
        canal = conexion.channel()
        _declarar(canal)
        datos = {
            "estado": "ok",
            "pendientes": canal.queue_declare(queue=COLA, passive=True).method.message_count,
            "fallidos": canal.queue_declare(queue=COLA_FALLIDOS, passive=True).method.message_count,
        }
        conexion.close()
        return datos
    except Exception as e:
        return {"estado": f"error: {type(e).__name__}"}
