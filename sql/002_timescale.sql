-- TimescaleDB only (Tiger Data has it pre-installed). app.initdb skips this file
-- with a warning if the extension is missing (e.g. plain local Postgres).
SELECT create_hypertable('flights', 'scheduled_out', if_not_exists => TRUE, migrate_data => TRUE);

-- AeroAPI Personal license: raw data may be stored for at most 30 days.
SELECT add_retention_policy('flights', INTERVAL '30 days', if_not_exists => TRUE);
