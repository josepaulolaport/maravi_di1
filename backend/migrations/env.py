"""Alembic environment for async SQLAlchemy with psycopg 3 (skill `db-migration`).

The URL is ``sqlalchemy.url`` when the caller sets it, otherwise ``DATABASE_URL`` as the
processes read it (`di1.platform.config.Settings`: the environment, then the `.env` files).

A caller that already runs an event loop (an async test or fixture) cannot let this module call
``asyncio.run``. It passes its own connection instead, through ``connection.run_sync``: a sync
function sets ``config.attributes["connection"]`` and calls ``command.upgrade``, and the migration
then runs on that connection, inside the caller's transaction.

Migrations are SQL-first: the revisions run reviewed SQL (``migrations/sql``) and autogenerate is
not used, so the context gets no ``target_metadata`` and none of autogenerate's options.
"""

from __future__ import annotations

import asyncio

from alembic import context
from pydantic import ValidationError
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool

from di1.platform.config import Settings

config = context.config


def _database_url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if url:
        return url
    try:
        return Settings().database_url.get_secret_value()
    except ValidationError as error:
        # Every setting is validated together; name the invalid ones (never their values).
        names = ", ".join(sorted({str(e["loc"][0]).upper() for e in error.errors()}))
        raise RuntimeError(
            f"invalid settings ({names}), in the environment or .env; DATABASE_URL is"
            " postgresql+psycopg://user:password@host:port/db"
        ) from error


def _configure(connection: Connection | None = None, url: str | None = None) -> None:
    context.configure(connection=connection, url=url, literal_binds=connection is None)


def run_migrations_offline() -> None:
    """Emit the SQL instead of running it (``alembic upgrade head --sql``)."""
    _configure(url=_database_url())
    with context.begin_transaction():
        context.run_migrations()


def _run_sync(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    engine = async_engine_from_config(section, prefix="sqlalchemy.", poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run_sync)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
elif (given := config.attributes.get("connection")) is not None:
    _run_sync(given)
else:
    asyncio.run(run_migrations_online())
