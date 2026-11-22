"""
La llamada a la API de NVIDIA, con tiempo maximo, reintentos y espera creciente.

La API de NVIDIA es compatible con el cliente de OpenAI: se cambia la base_url y
la clave, y el resto del codigo es igual.

Por que reintentar a mano y no dejar que lo haga la biblioteca: asi los
reintentos se ven en el log, se pueden medir y se pueden explicar. Y asi se
distingue lo que vale reintentar de lo que no.
"""
import os
import random
import time

from openai import APIConnectionError, APIStatusError, OpenAI

BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
MODELO = os.getenv("NVIDIA_MODEL", "")
TIMEOUT = float(os.getenv("NVIDIA_TIMEOUT", "20"))          # segundos por intento
INTENTOS = int(os.getenv("NVIDIA_INTENTOS", "4"))           # intentos en total
ESPERA_BASE = float(os.getenv("NVIDIA_ESPERA_BASE", "2"))   # 2, 4, 8 s mas un poco al azar
MAX_TOKENS = int(os.getenv("NVIDIA_MAX_TOKENS", "300"))

# max_retries=0: los reintentos los hacemos nosotros
cliente = OpenAI(base_url=BASE_URL, api_key=os.getenv("NVIDIA_API_KEY") or "sin-clave",
                 timeout=TIMEOUT, max_retries=0)


class LLMNoDisponible(Exception):
    """No respondio despues de los reintentos, o respondio algo que reintentar no arregla."""


def redactar(instruccion, contenido, dormir=time.sleep):
    for intento in range(1, INTENTOS + 1):
        espera_pedida = None
        try:
            r = cliente.chat.completions.create(
                model=MODELO,
                messages=[{"role": "system", "content": instruccion},
                          {"role": "user", "content": contenido}],
                max_tokens=MAX_TOKENS,
                temperature=0.3,
            )
            texto = (r.choices[0].message.content or "").strip()
            if not texto:
                raise LLMNoDisponible("respuesta vacia")
            return texto
        except APIStatusError as e:
            # 429 (limite de solicitudes) y 5xx (NVIDIA con problemas) se pueden
            # arreglar esperando. 401 (clave mala), 404 (modelo que no existe) o
            # 400 no: reintentar solo gasta cuota y tiempo.
            if e.status_code != 429 and e.status_code < 500:
                raise LLMNoDisponible(f"HTTP {e.status_code}") from e
            motivo = f"HTTP {e.status_code}"
            espera_pedida = e.response.headers.get("retry-after")
        except APIConnectionError as e:   # incluye el timeout
            motivo = type(e).__name__

        if intento == INTENTOS:
            raise LLMNoDisponible(f"{motivo} despues de {INTENTOS} intentos")

        espera = float(espera_pedida) if espera_pedida else ESPERA_BASE * 2 ** (intento - 1)
        # un poco al azar para que varios workers no reintenten en el mismo segundo
        espera += random.uniform(0, espera / 2)
        print(f'{{"servicio": "worker", "evento": "reintento", "motivo": "{motivo}", '
              f'"intento": {intento}, "espera_s": {espera:.1f}}}', flush=True)
        dormir(min(espera, 30))
