# Architecture

## Current design

Packets arrive at the ingest worker, which decodes, validates CRCs, and writes
Parquet to object storage. The API server reads from object storage and serves
the v2 REST API. There is no intermediate queue as of 2.0.

## DEPRECATED: the v1 monolith

This section describes the pre-2.0 architecture. The monolith was removed in
release 2.0 (2025-06-30) and no deployment runs it any more.

The monolith combined ingest, decode, and serving in a single process, with a
SQLite spool on local disk. Scaling it meant vertical scaling only, which is
why the split happened.

## Data retention

Raw packets are kept for 90 days, decoded Parquet indefinitely.
