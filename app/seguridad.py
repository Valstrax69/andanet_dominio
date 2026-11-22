"""
Clave de API y limite de solicitudes por minuto (EP3 2.5).

API_KEYS vacio = autenticacion apagada, que es lo que pasa en la defensa local
de EP2. En la EC2 el .env trae una o mas claves separadas por coma, y desde ese
momento una peticion sin clave recibe 401.

El contador del limite vive en la memoria del proceso. Sirve porque el dominio
corre con UNA replica. Si se escalara a dos, cada una contaria por su cuenta y
el limite habria que moverlo al gateway o a Redis: queda declarado como deuda.
"""
import hmac
import os
import threading
import time

from fastapi import Header, HTTPException, Request

API_KEYS = [k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()]
LIMITE_POR_MINUTO = int(os.getenv("LIMITE_POR_MINUTO", "60"))

_contadores = {}
_candado = threading.Lock()


def requiere_clave(request: Request, x_api_key: str | None = Header(default=None)):
    # compare_digest y no ==: comparar texto normalmente tarda distinto segun
    # cuantos caracteres coinciden, y eso filtra informacion de la clave
    if API_KEYS and (not x_api_key or not any(hmac.compare_digest(x_api_key, k) for k in API_KEYS)):
        raise HTTPException(status_code=401, detail="Falta la cabecera X-API-Key o no es valida")

    # Se cuenta por clave. Si la autenticacion esta apagada, por IP de origen.
    quien = (x_api_key or request.headers.get("x-real-ip")
             or (request.client.host if request.client else "?"))
    ventana = int(time.time() // 60)
    with _candado:
        for k in [k for k in _contadores if k[1] < ventana]:
            del _contadores[k]
        _contadores[(quien, ventana)] = usadas = _contadores.get((quien, ventana), 0) + 1

    if usadas > LIMITE_POR_MINUTO:
        raise HTTPException(status_code=429,
                            detail=f"Mas de {LIMITE_POR_MINUTO} solicitudes por minuto",
                            headers={"Retry-After": str(60 - int(time.time()) % 60)})


def autenticacion_activa():
    return bool(API_KEYS)
