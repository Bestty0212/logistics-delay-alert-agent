-- Additive migration: simulated clock + overdue alerts.
-- Apply once on an existing database (owner role), e.g.:
--   psql "$DATABASE_URL" -f db/migrations/001_simulation_and_overdue.sql
-- Fresh rebuild path (no migration needed): docker compose down -v &&
--   docker compose up -d && python scripts/import_data.py
--   (db/schema.sql already includes these objects on first init.)

CREATE TABLE IF NOT EXISTS simulation_clock (
    id SMALLINT PRIMARY KEY CHECK (id = 1),
    "current_date" DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS overdue_alerts (
    alert_id BIGSERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders (order_id) ON DELETE CASCADE,
    alert_date DATE NOT NULL,
    UNIQUE (order_id)
);

CREATE INDEX IF NOT EXISTS idx_overdue_alerts_alert_date
    ON overdue_alerts (alert_date);

GRANT SELECT ON TABLE simulation_clock TO agent_ro;
GRANT SELECT ON TABLE overdue_alerts TO agent_ro;
