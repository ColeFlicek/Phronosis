-- K8s Postgres init script — runs as postgres superuser on first container start.
-- Enables pgvector before schema.sql is applied.
CREATE EXTENSION IF NOT EXISTS vector;
