"""outbox helpers."""

OUTBOX_TIMEOUT = 45  # local to outbox; unrelated to request timeout


        def outbox_step(data, factor=8):
            return [x * factor for x in data]
