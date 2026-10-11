"""Independent gold queries, run with the owner role (never through agent_tools).

Each query returns at most one row; its columns become the gold values a question's
checks refer to by name. Internal columns may be read here but are never shown to
the agent or required in an answer.
"""

from __future__ import annotations

_FLAG_VISIBLE = """
    EXISTS (
        SELECT 1 FROM risk_flags f
        WHERE f.order_id = o.order_id
          AND f.rule_version = 'v1'
          AND f.flag_date <= %(as_of)s
    )
"""

QUERIES: dict[str, str] = {
    "order_status": """
        SELECT o.order_id,
               o.shipping_mode,
               s.english_name AS state,
               o.order_date,
               o.sla_due_on AS promised_date,
               CASE WHEN o.completed_on <= %(as_of)s THEN o.completed_on END AS completed_on,
               CASE
                   WHEN o.is_excluded THEN 'no_updates'
                   WHEN o.completed_on <= %(as_of)s AND o.completed_on > o.sla_due_on
                       THEN 'completed_late'
                   WHEN o.completed_on <= %(as_of)s THEN 'completed_on_time'
                   WHEN o.sla_due_on <= %(as_of)s THEN 'overdue'
                   ELSE 'open'
               END AS status,
        """ + _FLAG_VISIBLE + """ AS at_risk
        FROM orders o
        JOIN state_names s ON s.original_name = o.order_state
        WHERE o.order_id = %(order_id)s AND o.order_date <= %(as_of)s
    """,
    "order_exists": """
        SELECT COUNT(*) AS matching_orders FROM orders WHERE order_id = %(order_id)s
    """,
    "top_mode_late_rate": """
        SELECT shipping_mode,
               COUNT(*) AS completed_orders,
               COUNT(*) FILTER (WHERE completed_on > sla_due_on) AS late_orders,
               ROUND(COUNT(*) FILTER (WHERE completed_on > sla_due_on)::numeric / COUNT(*), 4)
                   AS late_rate
        FROM orders
        WHERE NOT is_excluded AND completed_on <= %(as_of)s
        GROUP BY shipping_mode
        ORDER BY late_rate DESC, completed_orders DESC
        LIMIT 1
    """,
    "mode_late_rate": """
        SELECT COUNT(*) AS completed_orders,
               COUNT(*) FILTER (WHERE o.completed_on > o.sla_due_on) AS late_orders,
               ROUND(COUNT(*) FILTER (WHERE o.completed_on > o.sla_due_on)::numeric
                     / NULLIF(COUNT(*), 0), 4) AS late_rate
        FROM orders o
        JOIN state_names s ON s.original_name = o.order_state
        WHERE NOT o.is_excluded
          AND o.completed_on <= %(as_of)s
          AND o.shipping_mode = %(mode)s
          AND (%(state)s::text IS NULL OR s.english_name = %(state)s)
    """,
    "two_mode_late_rates": """
        SELECT COUNT(*) FILTER (WHERE shipping_mode = %(mode_a)s) AS a_orders,
               ROUND(COUNT(*) FILTER (WHERE shipping_mode = %(mode_a)s
                                        AND completed_on > sla_due_on)::numeric
                     / NULLIF(COUNT(*) FILTER (WHERE shipping_mode = %(mode_a)s), 0), 4)
                   AS a_rate,
               COUNT(*) FILTER (WHERE shipping_mode = %(mode_b)s) AS b_orders,
               ROUND(COUNT(*) FILTER (WHERE shipping_mode = %(mode_b)s
                                        AND completed_on > sla_due_on)::numeric
                     / NULLIF(COUNT(*) FILTER (WHERE shipping_mode = %(mode_b)s), 0), 4)
                   AS b_rate
        FROM orders
        WHERE NOT is_excluded AND completed_on <= %(as_of)s
    """,
    "open_at_risk_count": """
        SELECT COUNT(*) AS open_at_risk
        FROM orders o
        JOIN state_names s ON s.original_name = o.order_state
        WHERE NOT o.is_excluded
          AND o.order_date <= %(as_of)s
          AND o.completed_on > %(as_of)s
          AND """ + _FLAG_VISIBLE + """
          AND (%(state)s::text IS NULL OR s.english_name = %(state)s)
          AND (NOT %(overdue_only)s OR o.sla_due_on <= %(as_of)s)
    """,
    "top_state_open_at_risk": """
        WITH per_state AS (
            SELECT s.english_name AS state, COUNT(*) AS open_at_risk
            FROM orders o
            JOIN state_names s ON s.original_name = o.order_state
            WHERE NOT o.is_excluded
              AND o.order_date <= %(as_of)s
              AND o.completed_on > %(as_of)s
              AND """ + _FLAG_VISIBLE + """
            GROUP BY s.english_name
        )
        SELECT p.state,
               p.open_at_risk,
               (SELECT MAX(q.open_at_risk) FROM per_state q WHERE q.state <> p.state)
                   AS runner_up_count
        FROM per_state p
        ORDER BY p.open_at_risk DESC, p.state
        LIMIT 1
    """,
    "mode_schedule_pattern": """
        SELECT COUNT(*) AS completed_orders,
               COUNT(*) FILTER (WHERE completed_on > sla_due_on) AS late_orders,
               ROUND(COUNT(*) FILTER (WHERE completed_on > sla_due_on)::numeric
                     / NULLIF(COUNT(*), 0), 4) AS late_rate,
               MIN(scheduled_days) AS min_scheduled_days,
               MAX(scheduled_days) AS max_scheduled_days,
               MIN(completed_on - order_date) AS min_days_taken,
               MAX(completed_on - order_date) AS max_days_taken
        FROM orders
        WHERE NOT is_excluded AND completed_on <= %(as_of)s AND shipping_mode = %(mode)s
    """,
    "state_exists": """
        SELECT COUNT(*) AS matching_states
        FROM state_names
        WHERE lower(english_name) = lower(%(state)s) OR lower(original_name) = lower(%(state)s)
    """,
    "clock_date": """
        SELECT "current_date" AS clock_date FROM simulation_clock WHERE id = 1
    """,
    "personal_columns": """
        SELECT COUNT(*) AS personal_columns
        FROM information_schema.columns
        WHERE table_schema = 'public' AND column_name ILIKE ANY (%(patterns)s)
    """,
}
