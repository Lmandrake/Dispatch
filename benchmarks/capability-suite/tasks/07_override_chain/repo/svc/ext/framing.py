"""framing helpers."""

FRAMING_TIMEOUT = 85  # local to framing; unrelated to request timeout


        def framing_step(data, factor=9):
            return [x * factor for x in data]
