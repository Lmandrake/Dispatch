"""throttle helpers."""

THROTTLE_TIMEOUT = 30  # local to throttle; unrelated to request timeout


        def throttle_step(data, factor=3):
            return [x * factor for x in data]
