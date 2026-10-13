-- Esquema de la base del asistente ANDA (Caso 2 - telco).
-- Lo aplica el servicio de carga antes de insertar los datos tratados.

CREATE TABLE IF NOT EXISTS clientes (
    cliente_id       TEXT PRIMARY KEY,
    fecha_alta       TEXT,
    plan             TEXT,
    tipo_servicio    TEXT,
    region           TEXT,
    segmento         TEXT,
    antiguedad_meses INTEGER,
    deuda_vigente    INTEGER,
    canal_preferido  TEXT,
    acepta_contacto  INTEGER
);

CREATE TABLE IF NOT EXISTS faq (
    articulo_id    TEXT PRIMARY KEY,
    pregunta       TEXT,
    respuesta      TEXT,
    categoria      TEXT,
    intencion      TEXT,
    vistas_12m     INTEGER,
    ultima_edicion TEXT
);

CREATE TABLE IF NOT EXISTS tickets (
    ticket_id         TEXT PRIMARY KEY,
    cliente_id        TEXT,
    canal             TEXT,
    fecha_apertura    TIMESTAMPTZ,
    fecha_cierre      TIMESTAMPTZ,
    categoria         TEXT,
    texto_consulta    TEXT,          -- ya enmascarado (RNF5)
    tiempo_espera_seg NUMERIC,
    resuelto          INTEGER,
    csat              NUMERIC,
    reabierto         INTEGER
);

-- Cada consulta resuelta por el asistente queda registrada (RF10, RNF12).
CREATE TABLE IF NOT EXISTS predicciones (
    id             BIGSERIAL PRIMARY KEY,
    texto_entrada  TEXT,             -- entrada enmascarada, nunca el crudo
    intencion      TEXT,
    confianza      REAL,
    modelo_version TEXT,
    derivada       BOOLEAN DEFAULT FALSE,
    creado_en      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tickets_cliente ON tickets (cliente_id);
CREATE INDEX IF NOT EXISTS idx_faq_intencion ON faq (intencion);
