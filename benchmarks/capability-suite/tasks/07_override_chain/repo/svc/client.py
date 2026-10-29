from . import settings


class RelayClient:
    def __init__(self, cfg=None):
        cfg = cfg or settings.load()
        self.timeout = cfg["timeout"]
        self.retries = cfg["retries"]
        self.port = cfg["port"]

    def describe(self):
        return f"relay:{self.port} timeout={self.timeout:g}s retries={self.retries}"
