# Runbook

## Restarting the ingest worker

    kubectl rollout restart deploy/ingest-worker -n ground

Watch for CRC error rate in the dashboard for five minutes afterwards.

## Restarting telemetry-forwarder

    kubectl rollout restart deploy/telemetry-forwarder -n ground

If the forwarder does not come back, check that `FORWARDER_BATCH_MS` is set in
the sidecar's env and that it landed on the same node as the worker.

## Draining a node

    kubectl drain <node> --ignore-daemonsets
