from fastapi.testclient import TestClient

from app.main import app

CLIENTE = TestClient(app)
CLAVE = {"X-API-Key": "clave-de-prueba"}
CUERPO = {"texto": "no tengo internet"}


def test_sin_clave_no_se_puede_predecir():
    # EP3 2.5: la API publica exige clave
    assert CLIENTE.post("/api/predict", json=CUERPO).status_code == 401


def test_una_clave_que_no_existe_tampoco():
    r = CLIENTE.post("/api/predict", json=CUERPO, headers={"X-API-Key": "inventada"})
    assert r.status_code == 401


def test_con_clave_pero_sin_texto_es_422():
    # La validacion del cuerpo ocurre despues de autenticar: 422, no 401
    r = CLIENTE.post("/api/predict", json={}, headers=CLAVE)
    assert r.status_code == 422


def test_el_texto_vacio_tambien_es_422():
    r = CLIENTE.post("/api/predict", json={"texto": ""}, headers=CLAVE)
    assert r.status_code == 422


def test_pasado_el_limite_por_minuto_responde_429():
    clave = {"X-API-Key": "clave-del-limite"}   # su propio contador
    codigos = [CLIENTE.post("/api/predict", json={}, headers=clave).status_code
               for _ in range(25)]
    assert 429 in codigos
    assert codigos.index(429) >= 20          # no antes del limite
    r = CLIENTE.post("/api/predict", json={}, headers=clave)
    assert r.headers.get("Retry-After") is not None


def test_health_no_pide_clave():
    # El healthcheck del contenedor no tiene la clave
    assert CLIENTE.get("/health").status_code == 200


def test_la_ruta_interna_no_pide_clave():
    # Caddy la bloquea desde internet; adentro la usa el worker sin clave.
    # Sin base responde 503, nunca 401.
    r = CLIENTE.put("/interno/respuesta/999999", json={"texto_llm": "x", "estado": "ok"})
    assert r.status_code in (404, 503)


def test_docs_se_publica():
    assert CLIENTE.get("/docs").status_code == 200
    assert CLIENTE.get("/openapi.json").status_code == 200
