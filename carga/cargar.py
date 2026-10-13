"""
Servicio de carga - corre una sola vez al levantar el sistema.

Aplica el esquema y carga las tablas tratadas (salida de preparar.py) en
Postgres. Usa INSERT ... ON CONFLICT DO NOTHING, asi que si el sistema se
levanta dos veces no duplica filas. Termina con codigo 0 (restart: "no").
"""
import csv
import os
import sys
import time
from pathlib import Path

import psycopg

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://anda:anda@db:5432/anda")
RAIZ = Path(__file__).resolve().parent.parent          # dominio/
SCHEMA = RAIZ / "sql" / "schema.sql"
DATOS = RAIZ / "datos" / "tratados"

# columna -> por tabla, y su clave primaria para el ON CONFLICT
TABLAS = {
    "clientes": (["cliente_id", "fecha_alta", "plan", "tipo_servicio", "region",
                  "segmento", "antiguedad_meses", "deuda_vigente", "canal_preferido",
                  "acepta_contacto"], "cliente_id"),
    "faq": (["articulo_id", "pregunta", "respuesta", "categoria", "intencion",
             "vistas_12m", "ultima_edicion"], "articulo_id"),
    "tickets": (["ticket_id", "cliente_id", "canal", "fecha_apertura", "fecha_cierre",
                 "categoria", "texto_consulta", "tiempo_espera_seg", "resuelto",
                 "csat", "reabierto"], "ticket_id"),
}


def esperar_db(intentos=30):
    for i in range(intentos):
        try:
            with psycopg.connect(DATABASE_URL, connect_timeout=3) as c:
                c.execute("SELECT 1")
            return
        except Exception as e:
            print(f"esperando la base ({i + 1}/{intentos})... {e}")
            time.sleep(2)
    sys.exit("La base no respondio a tiempo.")


def cargar_tabla(conn, tabla, cols, pk):
    archivo = DATOS / f"{tabla}.csv"
    with open(archivo, encoding="utf-8", newline="") as fh:
        filas = [[(row[c] if row[c] != "" else None) for c in cols]
                 for row in csv.DictReader(fh)]
    ph = ", ".join(["%s"] * len(cols))
    sql = (f'INSERT INTO {tabla} ({", ".join(cols)}) VALUES ({ph}) '
           f'ON CONFLICT ({pk}) DO NOTHING')
    with conn.cursor() as cur:
        cur.executemany(sql, filas)
    conn.commit()
    total = conn.execute(f"SELECT count(*) FROM {tabla}").fetchone()[0]
    print(f"{tabla}: {len(filas)} leidas, {total} en la tabla")


def main():
    esperar_db()
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute(SCHEMA.read_text(encoding="utf-8"))
        conn.commit()
        for tabla, (cols, pk) in TABLAS.items():
            cargar_tabla(conn, tabla, cols, pk)
    print("Carga completada.")


if __name__ == "__main__":
    main()
