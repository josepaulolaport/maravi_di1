---
name: db-migration
description: Create or verify the Alembic migration(s) for the Maravi DI1 PostgreSQL schema from docs/schema.sql. Integrator only — the initial revision in Wave 0, or a later one after a recorded user decision changes the schema.
---

# Database migrations (integrator only)

`docs/schema.sql` is the schema, and it applies cleanly to PostgreSQL 16 (see schema.md Status). **A schema change needs a recorded user decision first** (`record-decision`). Never change the schema to make code easier, and never let a lane create a revision. Revisions must never compete from the same parent.

## Initial revision (Wave 0)

1. **Configure Alembic** in `backend/migrations/`, for async SQLAlchemy:
   - `include_schemas=True`;
   - `compare_type=True`;
   - `target_metadata` built from every module's models.
2. **Create one initial revision** that runs `docs/schema.sql` as written. Copy the file in and read it from the revision; never retype it. Drop the file's own `BEGIN;`/`COMMIT;`, because Alembic manages the transaction.
3. **Write the downgrade** only where it is safe and documented (plan §3). Dropping the six schemas in reverse dependency order is acceptable for a fresh install.

## Verify, every time

Use a throwaway database, never the dev database:

- apply the migration to a fresh PostgreSQL 16 database;
- check that the models match the database;
- downgrade and upgrade again, where a downgrade exists;
- run the constraint and integration tests against that database.

Report each result in the PR with its real output.
