from fastapi.testclient import TestClient

from app.main import app, quiere_humano
from app.plantillas import PLANTILLAS

client = TestClient(app)
INTENCIONES = {"facturacion", "falla_conexion", "cambio_plan", "visita", "anulacion", "otra"}


def test_deriva_cuando_pide_humano():
    # No toca base ni IA: el pedido de humano se resuelve de inmediato (RNF11)
    r = client.post("/api/chat", json={"texto": "quiero hablar con una persona"})
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["derivar"] is True
    assert cuerpo["respuesta"]


def test_quiere_humano_detecta_variantes():
    assert quiere_humano("necesito un ejecutivo")
    assert quiere_humano("pasame con un agente")
    assert not quiere_humano("cuanto es mi saldo")


def test_plantillas_cubren_todas_las_intenciones():
    for i in INTENCIONES:
        assert PLANTILLAS.get(i)


def test_rechaza_texto_vacio():
    r = client.post("/api/chat", json={"texto": ""})
    assert r.status_code == 422
