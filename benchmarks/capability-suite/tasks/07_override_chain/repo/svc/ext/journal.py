"""journal helpers."""

JOURNAL_TIMEOUT = 33  # local to journal; unrelated to request timeout


        def journal_step(data, factor=5):
            return [x * factor for x in data]
