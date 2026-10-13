"""Respuesta al cliente a partir de la intencion.

La respuesta sale de la base de conocimiento (tabla faq), que negocio puede
editar sin desplegar codigo (RF11). Si no hay articulo, se usa un texto base.
"""

# Texto base por si la FAQ no tiene articulo para esa intencion.
PLANTILLAS = {
    "facturacion": "Puedes revisar tu saldo y la fecha de vencimiento en la seccion Mi Cuenta de la app o del sitio web.",
    "falla_conexion": "Reinicia el router, revisa las luces y confirma que no haya un corte en tu zona. Si sigue, agendamos una visita.",
    "cambio_plan": "Puedes cambiar de plan desde la app en Mi Plan. El cambio se aplica en tu proximo ciclo de facturacion.",
    "visita": "Puedes consultar el estado y la hora estimada de tu visita tecnica en la seccion Agenda de la app.",
    "anulacion": "Para dar de baja un servicio te derivo con un ejecutivo, que revisara tu caso.",
    "otra": "Gracias por tu mensaje. Si necesitas algo mas especifico, puedo derivarte con un ejecutivo.",
}

DERIVACION = "Te estoy derivando con un ejecutivo para que continue tu atencion."


def buscar_respuesta(conn, intencion):
    try:
        fila = conn.execute(
            "SELECT respuesta FROM faq WHERE intencion = %s AND respuesta <> '' "
            "ORDER BY vistas_12m DESC LIMIT 1",
            (intencion,),
        ).fetchone()
        if fila and fila[0]:
            return fila[0]
    except Exception:
        pass
    return PLANTILLAS.get(intencion, PLANTILLAS["otra"])
