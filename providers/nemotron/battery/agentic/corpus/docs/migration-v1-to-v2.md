# Migrating from v1 to v2

Status: COMPLETED 2025-08-30. Every cluster (prod, staging, dev) is on v2 and
no v1 deployment remains. This guide is retained only until the next docs sweep.

## Step 1 — freeze writes to the monolith
## Step 2 — dual-write to the v2 API
## Step 3 — backfill Parquet from the SQLite spool
## Step 4 — cut over readers
## Step 5 — decommission the monolith
