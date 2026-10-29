"""handshake helpers."""

HANDSHAKE_TIMEOUT = 42  # local to handshake; unrelated to request timeout


        def handshake_step(data, factor=8):
            return [x * factor for x in data]
