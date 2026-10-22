import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Add src/ to sys.path so we can import meridian.config
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
)

from meridian.config import settings

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

ALEMBIC_PLACEHOLDER_URL = "driver://user:pass@localhost/dbname"
ALEMBIC_GUARD_ATTRIBUTE = "meridian_guard_validated_url"

validated_url = config.attributes.get(ALEMBIC_GUARD_ATTRIBUTE)
current_ini_url = config.get_main_option("sqlalchemy.url")

if validated_url:
    # State A: Explicitly validated caller URL from test guard
    if current_ini_url != validated_url:
        raise RuntimeError(
            "Alembic safety violation: config sqlalchemy.url does not match "
            "the guard-validated URL signal."
        )
elif current_ini_url in (ALEMBIC_PLACEHOLDER_URL, settings.database_url):
    # State B: Standalone Alembic CLI execution with exact repository placeholder
    # or already-resolved settings database URL
    if not settings.database_url:
        raise RuntimeError(
            "Alembic configuration error: settings.database_url is empty."
        )
    if current_ini_url == ALEMBIC_PLACEHOLDER_URL:
        config.set_main_option(
            "sqlalchemy.url", settings.database_url.replace("%", "%%")
        )
else:
    # State C: Unexpected, unvalidated, or untrusted configuration
    raise RuntimeError(
        "Alembic safety violation: Untrusted or unexpected database URL in "
        "configuration. Direct non-placeholder URLs require explicit test guard "
        "validation."
    )

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = None

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
