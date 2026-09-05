"""Alembic environment.

Database URL is sourced from application settings (``.env`` / env vars) so
secrets are never committed here.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config.settings import get_settings
from app.infrastructure.database import models as _models  # noqa: F401  (registers ORM models)
from app.infrastructure.database.postgres import Base

config = context.config
if config.config_file_name is not None and os.getenv("ALEMBIC_SKIP_LOG_CONFIG") != "1":
    # ``disable_existing_loggers=False`` is essential: without it, fileConfig
    # disables every logger the host process (API / worker / tests) configured
    # before migrations ran, silencing the application for its entire lifetime.
    # Programmatic runs (app startup) skip fileConfig entirely so the host keeps
    # the logging configuration it installed.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

database_url = get_settings().database_url
config.set_main_option("sqlalchemy.url", database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
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