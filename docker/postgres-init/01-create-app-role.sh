#!/bin/bash
set -e

if [ -z "$APP_DB_USER" ] || [ -z "$APP_DB_PASSWORD" ]; then
    echo "ERROR: APP_DB_USER or APP_DB_PASSWORD is not set. Skipping app role creation."
    exit 1
fi

if [ -z "$POSTGRES_USER" ] || [ -z "$POSTGRES_DB" ]; then
    echo "ERROR: POSTGRES_USER or POSTGRES_DB is not set. Skipping app role creation."
    exit 1
fi

echo "Creating application role: $APP_DB_USER"

psql -v ON_ERROR_STOP=1 --host="${POSTGRES_HOST:-localhost}" --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '$APP_DB_USER') THEN
            CREATE ROLE $APP_DB_USER WITH LOGIN PASSWORD '$APP_DB_PASSWORD' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
        ELSE
            RAISE NOTICE 'Role % already exists, skipping creation.', '$APP_DB_USER';
        END IF;
    END
    \$\$;
EOSQL
