"""Reaper: a background thread for time-driven maintenance.

Every ``interval`` seconds it calls ``broker.reap()`` (expire overdue
leases), and every ``purge_every`` rounds ``broker.purge()``. ``tick()`` does
one round synchronously and is what tests and the CLI call.

``reserve`` also expires overdue leases inline, so a stopped reaper delays
redelivery only while no worker is polling.
"""

import threading
from typing import Dict, List, Optional

from .errors import BrokerClosed


class Reaper:
    def __init__(self, broker, interval: float = 1.0, purge_every: int = 60):
        if interval <= 0:
            raise ValueError("interval must be > 0")
        self.broker = broker
        self.interval = interval
        self.purge_every = max(1, int(purge_every))
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.rounds = 0
        self.expired_total = 0
        self.purged_total = 0

    def tick(self) -> Dict[str, List[str]]:
        expired = self.broker.reap()
        self.rounds += 1
        self.expired_total += len(expired)
        purged: List[str] = []
        if self.rounds % self.purge_every == 0:
            purged = self.broker.purge()
            self.purged_total += len(purged)
        return {"expired": expired, "purged": purged}

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.tick()
            except BrokerClosed:
                return

    def start(self) -> "Reaper":
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="taskmill-reaper", daemon=True)
            self._thread.start()
        return self

    def stop(self, wait: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(wait)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
