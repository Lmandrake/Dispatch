# Orbital Telemetry Pipeline

Ingests spacecraft downlink packets, decodes them, and serves them over a REST
API. Runs on the ground-segment Kubernetes cluster.

## Quick start

    pip install -e .
    telem serve --config configs/ground.yaml

## Roadmap

- [x] Q1 2025 — Replace the CSV ingest path with Parquet (shipped in 1.4)
- [x] Q2 2025 — Ship the v2 REST API (shipped in 2.0)
- [x] Q3 2025 — Retire the vendored protobuf fork (shipped in 2.1)
- [ ] Q4 2026 — Streaming downlink support
- [ ] Q1 2027 — Multi-mission tenancy

## Legacy notes

The `telemetry-forwarder` sidecar was decommissioned in March 2026 when the
ingest worker absorbed its responsibilities. The notes below are kept only for
historical reference and no longer describe any running system.

Forwarder tuning used to require setting `FORWARDER_BATCH_MS` and pinning the
sidecar to the same node as the worker. Neither knob exists any more.

## Support

File issues in the ground-segment tracker.
