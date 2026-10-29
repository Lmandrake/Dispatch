"""Runtime: a broker plus the threads that make it a service.

``Runtime(data_dir, ...)`` opens a :class:`Broker` on ``data_dir`` (reading
``<data_dir>/taskmill.json`` for configuration when it exists and no config
is given), and ``start()`` starts a WorkerPool, a Reaper and, if any
schedules are configured, a Scheduler. ``stop()`` stops them in reverse
order, takes a final checkpoint and closes the broker.

This is what ``taskmill run`` and ``taskmill serve`` use.
"""

import json
import os
from typing import List, Optional

from .broker import Broker
from .config import BrokerConfig
from .handlers import Registry, default_registry
from .reaper import Reaper
from .scheduler import Schedule, Scheduler, load_schedules
from .worker import WorkerPool

CONFIG_NAME = "taskmill.json"
SCHEDULES_NAME = "schedules.json"


def load_config(data_dir: Optional[str]) -> BrokerConfig:
    if data_dir:
        path = os.path.join(data_dir, CONFIG_NAME)
        if os.path.exists(path):
            return BrokerConfig.from_file(path)
    return BrokerConfig()


def load_schedule_file(data_dir: Optional[str]) -> List[Schedule]:
    if not data_dir:
        return []
    path = os.path.join(data_dir, SCHEDULES_NAME)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return load_schedules(json.load(fh))


class Runtime:
    def __init__(self, data_dir: Optional[str], config: Optional[BrokerConfig] = None, clock=None,
                 registry: Optional[Registry] = None, concurrency: int = 4,
                 reaper_interval: float = 1.0, schedules: Optional[List[Schedule]] = None,
                 queues=None, poll: float = 0.1, heartbeat_interval: Optional[float] = None):
        self.broker = Broker(data_dir, config or load_config(data_dir), clock=clock)
        self.registry = registry or default_registry()
        self.pool = WorkerPool(self.broker, self.registry, concurrency=concurrency, queues=queues,
                               poll=poll, heartbeat_interval=heartbeat_interval)
        self.reaper = Reaper(self.broker, interval=reaper_interval)
        if schedules is None:
            schedules = load_schedule_file(data_dir)
        self.scheduler = Scheduler(self.broker, schedules) if schedules else None
        self._started = False

    def start(self) -> "Runtime":
        if not self._started:
            self._started = True
            self.reaper.start()
            if self.scheduler is not None:
                self.scheduler.start()
            self.pool.start()
        return self

    def stop(self, checkpoint: bool = True) -> None:
        if self._started:
            self.pool.stop()
            if self.scheduler is not None:
                self.scheduler.stop()
            self.reaper.stop()
        if checkpoint and not self.broker.closed and self.broker.data_dir:
            self.broker.checkpoint()
        self.broker.close()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
