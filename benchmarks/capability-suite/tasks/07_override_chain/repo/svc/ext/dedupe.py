"""dedupe helpers."""

DEDUPE_TIMEOUT = 49  # local to dedupe; unrelated to request timeout


        def dedupe_step(data, factor=2):
            return [x * factor for x in data]
