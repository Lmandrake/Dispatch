"""Tiny row-transformation pipeline."""
from .record import Record


class Pipeline:
    steps = []
    options = {"skip_errors": False}

    def __init__(self, name, **options):
        self.name = name
        self.options.update(options)

    def step(self, fn):
        """Register ``fn(dict) -> dict`` as the next step. Usable as a decorator."""
        self.steps.append(fn)
        return fn

    def run(self, rows):
        out, errors = [], []
        for row in rows:
            rec = Record(row)
            try:
                for fn in self.steps:
                    rec.data = fn(rec.data)
                    rec.note(fn.__name__)
            except Exception as exc:  # noqa: BLE001
                if not self.options["skip_errors"]:
                    raise
                errors.append((row, exc))
                continue
            out.append(rec)
        return out, errors
