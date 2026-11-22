import os

# Se fijan ANTES de importar la app: app.seguridad lee estas variables al cargar
os.environ.setdefault("API_KEYS", "clave-de-prueba,clave-del-limite")
os.environ.setdefault("LIMITE_POR_MINUTO", "20")
os.environ.setdefault("RABBITMQ_URL", "")        # sin cola en las pruebas
