# Architecture (Step 1 baseline)

    app/
      config.py          validated settings (single source of truth)
      logging_config.py  request-id logging
      database.py        engine, sessions, Base, health check
      models/            mixins now; domain tables from Step 2 on
      api/health.py      /health (liveness), /ready (database)
      main.py            create_app() factory
    alembic/             migrations (baseline 0001)
    tests/               isolated in-memory DB fixtures

Rules carried through all 15 steps: independence from any connected system,
workspace isolation, permissions, approvals, one execution boundary, audit.
Every new table uses UUIDPrimaryKeyMixin + TimestampMixin and gets a migration.
