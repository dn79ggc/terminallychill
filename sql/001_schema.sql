-- Base schema. Works on plain PostgreSQL and on Tiger Data.
CREATE TABLE IF NOT EXISTS flights (
    uid            TEXT        NOT NULL,   -- provider flight id, or source:ident:scheduled_out
    ident          TEXT        NOT NULL,   -- e.g. DL123
    operator       TEXT,
    gate           TEXT,                   -- e.g. B22
    concourse      TEXT,                   -- first letter of gate: T A B C D E F (NULL if unknown)
    terminal       TEXT,                   -- provider metadata only (N / S), NOT a concourse
    aircraft_type  TEXT,                   -- ICAO type, e.g. B739
    scheduled_out  TIMESTAMPTZ NOT NULL,   -- stored in UTC
    estimated_out  TIMESTAMPTZ,
    delay_s        INTEGER,                -- seconds, negative = early
    cancelled      BOOLEAN     NOT NULL DEFAULT FALSE,
    source         TEXT        NOT NULL,   -- aeroapi | aviationstack | snapshot
    fetched_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (uid, scheduled_out)       -- must include the partition column for hypertables
);
