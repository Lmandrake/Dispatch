"""inbox helpers."""

INBOX_TIMEOUT = 48  # local to inbox; unrelated to request timeout


        def inbox_step(data, factor=3):
            return [x * factor for x in data]
