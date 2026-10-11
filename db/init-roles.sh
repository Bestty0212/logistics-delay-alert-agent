#!/bin/bash
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${AGENT_RO_USER}') THEN
            CREATE ROLE ${AGENT_RO_USER} LOGIN PASSWORD '${AGENT_RO_PASSWORD}';
        END IF;
    END
    \$\$;
EOSQL
