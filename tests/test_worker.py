"""
Pruebas del worker sin RabbitMQ, sin NVIDIA y sin dominio: cada pieza externa
se reemplaza por un doble, asi corren en CI sin credenciales ni red.
"""
import os

os.environ.setdefault("NVIDIA_MODEL", "modelo-de-prueba")

import httpx       # noqa: E402
import openai      # noqa: E402
import pytest      # noqa: E402

from worker import llm, worker   # noqa: E402

PEDIDO = {"id": "7", "instruccion": "Redacta.", "contenido": '{"intencion": "facturacion"}'}


def error_http(codigo):
    respuesta = httpx.Response(codigo, request=httpx.Request("POST", "https://integrate.api.nvidia.com/v1"))
    return openai.APIStatusError(f"HTTP {codigo}", response=respuesta, body=None)


class NvidiaFalso:
    """Responde como cliente.chat.completions.create: primero los errores, despues texto."""

    def __init__(self, errores=(), texto="Tu boleta vence el dia que indica el detalle."):
        self.errores, self.texto, self.llamadas = list(errores), texto, 0
        self.chat = self.completions = self

    def create(self, **_):
        self.llamadas += 1
        if self.errores:
            raise self.errores.pop(0)
        mensaje = type("M", (), {"content": self.texto})
        return type("R", (), {"choices": [type("C", (), {"message": mensaje})]})


class DominioFalso:
    """Hace de ruta interna del dominio: guarda lo que el worker le entrega."""

    def __init__(self, estado="pendiente"):
        self.estado, self.entregas = estado, []

    def get(self, url, timeout):
        if self.estado is None:
            return httpx.Response(404, json={"detail": "No existe"},
                                  request=httpx.Request("GET", url))
        return httpx.Response(200, json={"estado": self.estado},
                              request=httpx.Request("GET", url))

    def put(self, url, json, timeout):
        self.entregas.append(json)
        return httpx.Response(200, json={"ok": True}, request=httpx.Request("PUT", url))


@pytest.fixture
def esperas():
    return []


def test_la_respuesta_normal_se_entrega_como_listo(monkeypatch):
    monkeypatch.setattr(llm, "cliente", NvidiaFalso())
    dominio = DominioFalso()
    assert worker.procesar(PEDIDO, cliente=dominio) == "listo"
    assert dominio.entregas[0]["estado"] == "listo"
    assert dominio.entregas[0]["texto"].startswith("Tu boleta")


def test_si_nvidia_falla_la_prediccion_sigue_y_queda_degradada(monkeypatch, esperas):
    # Lo que exige el enunciado: si NVIDIA falla, la prediccion sigue funcionando.
    # El worker no revienta ni deja el mensaje dando vueltas: entrega "degradado".
    falso = NvidiaFalso(errores=[error_http(429)] * llm.INTENTOS)
    monkeypatch.setattr(llm, "cliente", falso)
    dominio = DominioFalso()
    estado = worker.procesar(
        PEDIDO, redactar=lambda i, c: llm.redactar(i, c, dormir=esperas.append), cliente=dominio)
    assert estado == "degradado"
    assert falso.llamadas == llm.INTENTOS
    assert len(esperas) == llm.INTENTOS - 1
    assert dominio.entregas[0]["estado"] == "degradado"
    assert "429" in dominio.entregas[0]["motivo"]


def test_reintenta_con_espera_creciente_y_despues_responde(monkeypatch, esperas):
    monkeypatch.setattr(llm, "cliente", NvidiaFalso(errores=[error_http(429), error_http(503)]))
    assert llm.redactar("instruccion", "contenido", dormir=esperas.append)
    assert len(esperas) == 2
    assert esperas[1] > esperas[0] * 1.3      # la espera crece


def test_una_clave_invalida_no_se_reintenta(monkeypatch, esperas):
    # Reintentar un 401 solo gasta cuota: el error no se arregla esperando
    falso = NvidiaFalso(errores=[error_http(401)])
    monkeypatch.setattr(llm, "cliente", falso)
    with pytest.raises(llm.LLMNoDisponible, match="401"):
        llm.redactar("instruccion", "contenido", dormir=esperas.append)
    assert falso.llamadas == 1
    assert esperas == []


def test_no_se_repite_una_llamada_ya_hecha():
    def no_deberia_llamarse(*_):
        raise AssertionError("llamo al LLM otra vez")
    dominio = DominioFalso(estado="listo")
    assert worker.procesar(PEDIDO, redactar=no_deberia_llamarse, cliente=dominio) == "listo"
    assert dominio.entregas == []


def test_una_prediccion_borrada_se_descarta_sin_llamar_al_llm():
    def no_deberia_llamarse(*_):
        raise AssertionError("llamo al LLM para una prediccion que no existe")
    dominio = DominioFalso(estado=None)
    assert worker.procesar(PEDIDO, redactar=no_deberia_llamarse, cliente=dominio) == "descartado"
    assert dominio.entregas == []
