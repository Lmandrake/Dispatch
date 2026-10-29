class Record:
    """A row flowing through a pipeline, with an audit trail of applied steps."""

    def __init__(self, data, history=[]):
        self.data = dict(data)
        self.history = history

    def note(self, step_name):
        self.history.append(step_name)

    def __repr__(self):
        return f"Record({self.data!r}, history={self.history!r})"
