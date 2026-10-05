# BETA AID Data API

Read-only HTTP API for the platform serving registry and the knowledge
active set. It connects only as `app_reader`, runs every query in a
read-only transaction, and returns counts, digests, and document
metadata. Customer rows, chunk text, and embeddings are not selected.

## Run

From the repository root:

```bash
make data-api-dev
```

Listens on `http://127.0.0.1:8090`. `APP_READER_DB_PASSWORD` is taken from
the environment, or from `platform/docker/.env` when that variable is
unset. A worktree does not contain that git-ignored file: copy it from
the main checkout with `cp -p`, or set `DATA_API_STACK_ENV` to its path.
Do not print or commit the file.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATA_API_CORS_ORIGINS` | `http://localhost:3000` | Comma-separated browser origins |
| `APP_READER_DB_PASSWORD` | filled from the stack env file | `app_reader` password |
| `LATAM_PG_CORE_HOST` | `127.0.0.1` | Postgres host (`latam_platform.ops.pg`) |
| `LATAM_PG_CORE_PORT` | `5433` on loopback | Postgres port |
| `DATA_API_STACK_ENV` | `platform/docker/.env` | File used to fill missing keys |

## Endpoints

`GET /health` returns `{"ok": true, "service": "beta-aid-data-api"}` and
does not open a database connection.

## Tests

```bash
cd platform/services/data_api && uv run pytest
```

Unit tests use a fake connection and always run. Tests marked
`integration` talk to pg-core and skip when it is not reachable.
