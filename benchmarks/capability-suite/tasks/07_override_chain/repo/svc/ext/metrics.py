"""metrics helpers."""

METRICS_TIMEOUT = 14  # local to metrics; unrelated to request timeout


        def metrics_step(data, factor=1):
            return [x * factor for x in data]
