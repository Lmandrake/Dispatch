HEALTHCHECK_TIMEOUT = 30  # independent of the relay timeout; do not couple


def probe(fn):
    return fn(timeout=HEALTHCHECK_TIMEOUT)
