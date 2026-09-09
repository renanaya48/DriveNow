"""Alembic environment.

The database URL comes from the application settings (one source of truth), not
from alembic.ini. Importing ``app.models`` registers every table on
``Base.metadata`` so ``--autogenerate`` sees the full schema.
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.core.config import get_settings
from app.models import Base

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers=False: `alembic upgrade` runs in-process (Docker
    # entrypoint, tests) and the default (True) would switch off the app's own
    # loggers for the rest of the process.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Resolve the DB URL: an explicit value on the config wins (tests / `alembic -x`),
# otherwise fall back to application settings. Escape % for ConfigParser.
_url = config.get_main_option("sqlalchemy.url") or get_settings().database_url
config.set_main_option("sqlalchemy.url", _url.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without a DBAPI connection (emit SQL)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # render_as_batch keeps ALTERs working on SQLite (used in tests).
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
