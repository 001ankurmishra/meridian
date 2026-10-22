#!/bin/bash
set -e

if [ "$POSTGRES_DB" = "meridian_test" ] || [ "$DISPOSABLE_TEST_DB" = "true" ]; then
    echo "Configuring disposable marker on test database: $POSTGRES_DB"
    psql -v ON_ERROR_STOP=1 ${POSTGRES_HOST:+--host="$POSTGRES_HOST"} --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
        ALTER DATABASE "$POSTGRES_DB" SET meridian.disposable_test_db = 'on';
EOSQL
else
    echo "Skipping disposable test database marker for non-test database: $POSTGRES_DB"
fi
