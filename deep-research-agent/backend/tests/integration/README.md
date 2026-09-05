# Integration tests

These tests hit a real PostgreSQL database and are skipped automatically when the
database is unreachable.

## Running Postgres

The Docker Compose file starts PostgreSQL (and Redis) with credentials matching
the default `DATABASE_URL`:

```bash
cd deep-research-agent
docker compose -f docker/docker-compose.yml up -d postgres
```

## Running the integration tests

```bash
cd backend
uv run pytest tests/integration -v
```

## Notes

- Tests apply the ORM schema (`create_all`) to a scratch schema each run; the
  production `alembic` migration is validated separately via `alembic upgrade head`.
- No SQLite is used as a stand-in for PostgreSQL.