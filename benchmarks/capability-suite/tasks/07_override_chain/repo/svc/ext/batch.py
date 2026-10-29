"""batch helpers."""

BATCH_TIMEOUT = 39  # local to batch; unrelated to request timeout


        def batch_step(data, factor=9):
            return [x * factor for x in data]
