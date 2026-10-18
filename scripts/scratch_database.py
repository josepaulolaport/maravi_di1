"""Create or drop a throwaway PostgreSQL database for the migration smoke check (make test-backend).

Usage, from ``backend/`` (it needs the backend's psycopg and SQLAlchemy):

    uv run --frozen python ../scripts/scratch_database.py create <admin_url> <name>  # prints URL
    uv run --frozen python ../scripts/scratch_database.py drop <admin_url> <name>

``admin_url`` is the SQLAlchemy URL of ``TEST_DATABASE_URL``. The smoke check never migrates the
admin database itself, so a server the developer points ``TEST_DATABASE_URL`` at is left as found.
"""

from __future__ import annotations

import sys

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url


def main(action: str, admin_url: str, name: str) -> None:
    url = make_url(admin_url)
    libpq = url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(libpq, autocommit=True) as admin:
        if action == "create":
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            sys.stdout.write(url.set(database=name).render_as_string(hide_password=False) + "\n")
        elif action == "drop":
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )
        else:
            raise SystemExit(f"unknown action {action!r}: use create or drop")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
