"""keepalive helpers."""

KEEPALIVE_TIMEOUT = 69  # local to keepalive; unrelated to request timeout


        def keepalive_step(data, factor=6):
            return [x * factor for x in data]
