"""Conexion a Postgres. El dominio es el unico servicio que toca la base."""
import os

import psycopg

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://anda:anda@db:5432/anda")


def conectar():
    return psycopg.connect(DATABASE_URL, connect_timeout=3)


def db_viva():
    try:
        with conectar() as c:
            c.execute("SELECT 1")
        return True
    except Exception:
        return False
