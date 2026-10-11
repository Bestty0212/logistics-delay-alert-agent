-- Tables and grants for the logistics delay agent.
-- Runs as POSTGRES_USER on first container init.

CREATE TABLE state_names (
    original_name TEXT PRIMARY KEY,
    english_name TEXT NOT NULL UNIQUE
);

CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY,
    order_date DATE NOT NULL,
    shipping_mode TEXT NOT NULL,
    scheduled_days INTEGER NOT NULL,
    actual_days INTEGER NOT NULL,
    completed_on DATE,
    sla_due_on DATE NOT NULL,
    order_state TEXT NOT NULL REFERENCES state_names (original_name),
    delivery_status TEXT NOT NULL,
    order_status TEXT NOT NULL,
    late_label BOOLEAN,
    is_excluded BOOLEAN NOT NULL,
    customer_segment TEXT NOT NULL,
    payment_type TEXT NOT NULL,
    CHECK (
        (is_excluded AND completed_on IS NULL AND late_label IS NULL)
        OR
        (NOT is_excluded AND completed_on IS NOT NULL AND late_label IS NOT NULL)
    ),
    CHECK (sla_due_on = order_date + scheduled_days),
    CHECK (is_excluded OR completed_on = order_date + actual_days)
);

CREATE TABLE order_items (
    order_item_id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders (order_id) ON DELETE CASCADE,
    department_name TEXT NOT NULL,
    category_name TEXT NOT NULL,
    product_name TEXT NOT NULL,
    product_price NUMERIC NOT NULL,
    quantity INTEGER NOT NULL,
    discount_rate NUMERIC NOT NULL
);

CREATE TABLE events (
    event_id BIGSERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders (order_id) ON DELETE CASCADE,
    event_type TEXT NOT NULL CHECK (
        event_type IN ('order_placed', 'sla_due', 'order_completed')
    ),
    event_date DATE NOT NULL,
    UNIQUE (order_id, event_type)
);

CREATE TABLE risk_flags (
    risk_flag_id BIGSERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders (order_id) ON DELETE CASCADE,
    flag_date DATE NOT NULL,
    rule_version TEXT NOT NULL,
    reason TEXT NOT NULL,
    UNIQUE (order_id, rule_version)
);

-- Exactly one row when replay has started; absent means "replay not started"
-- (readers must error — never fall back to the real date).
CREATE TABLE simulation_clock (
    id SMALLINT PRIMARY KEY CHECK (id = 1),
    "current_date" DATE NOT NULL
);

CREATE TABLE overdue_alerts (
    alert_id BIGSERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders (order_id) ON DELETE CASCADE,
    alert_date DATE NOT NULL,
    UNIQUE (order_id)
);

-- Time-based train/test splits and as-of filtering.
CREATE INDEX idx_orders_order_date ON orders (order_date);
-- State filters and join path to state_names.
CREATE INDEX idx_orders_order_state ON orders (order_state);
-- Look up items for an order.
CREATE INDEX idx_order_items_order_id ON order_items (order_id);
-- Replay and as-of event scans by date.
CREATE INDEX idx_events_event_date ON events (event_date);
-- List risk flags for an order.
CREATE INDEX idx_risk_flags_order_id ON risk_flags (order_id);
-- As-of and "how early" reporting for overdue alerts.
CREATE INDEX idx_overdue_alerts_alert_date ON overdue_alerts (alert_date);

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO agent_ro;

GRANT SELECT ON TABLE
    orders,
    order_items,
    events,
    risk_flags,
    state_names,
    simulation_clock,
    overdue_alerts
TO agent_ro;
