#!/bin/bash
set -e

if [ -z "$LOADER_DB_USER" ] || [ -z "$LOADER_DB_PASSWORD" ]; then
    echo "ERROR: LOADER_DB_USER or LOADER_DB_PASSWORD is not set. Skipping loader role creation."
    exit 1
fi

if [ -z "$POSTGRES_USER" ] || [ -z "$POSTGRES_DB" ]; then
    echo "ERROR: POSTGRES_USER or POSTGRES_DB is not set. Skipping loader role creation."
    exit 1
fi

echo "Creating loader role: $LOADER_DB_USER"

psql -v ON_ERROR_STOP=1 ${POSTGRES_HOST:+--host="$POSTGRES_HOST"} --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '$LOADER_DB_USER') THEN
            CREATE ROLE $LOADER_DB_USER WITH LOGIN PASSWORD '$LOADER_DB_PASSWORD' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
        ELSE
            RAISE NOTICE 'Role % already exists, skipping creation.', '$LOADER_DB_USER';
        END IF;
    END
    \$\$;
EOSQL
