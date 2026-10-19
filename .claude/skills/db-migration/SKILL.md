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

## Later revisions (after a recorded decision)

1. **Update `docs/schema.sql` first**, so it stays the complete schema: the result of every revision, not the text of one.
2. **Never edit a released revision.** `tests/architecture/test_migration_sql.py` pins `0001_initial.sql` by hash.
3. **Write the revision as reviewed SQL** in `migrations/sql/NNNN_<name>.sql` (and `NNNN_<name>_downgrade.sql`), run from `migrations/versions/NNNN_<name>.py` exactly like 0001. No `BEGIN;`/`COMMIT;`: Alembic owns the transaction.
4. **Carry existing rows over** explicitly in the SQL, and say how in its comments; refuse to run while a processing job is active if it touches the tables a job writes (`processing.requests`, `processing.date_status`, the published `portfolio` tables).
5. **Downgrade** restores the previous revision exactly and refuses to lose rows unless `-x allow_data_loss=true` is given.
6. **Extend the equivalence test** (`tests/integration/test_migrations_match_schema.py`): the revisions must build exactly the columns, constraints and indexes that `docs/schema.sql` builds, and a downgrade must give back the previous catalog.

## Verify, every time

Use a throwaway database, never the dev database:

- apply the migration to a fresh PostgreSQL 16 database;
- check that the models match the database;
- downgrade and upgrade again, where a downgrade exists;
- run the constraint and integration tests against that database.

Report each result in the PR with its real output.
