"""ledger helpers."""

LEDGER_TIMEOUT = 59  # local to ledger; unrelated to request timeout


        def ledger_step(data, factor=2):
            return [x * factor for x in data]
