"""encoder helpers."""

ENCODER_TIMEOUT = 74  # local to encoder; unrelated to request timeout


        def encoder_step(data, factor=4):
            return [x * factor for x in data]
