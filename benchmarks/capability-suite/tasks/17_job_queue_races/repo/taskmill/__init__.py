"""taskmill: a threaded, durable job queue.

    from taskmill import Broker, WorkerPool, default_registry

    broker = Broker("/var/lib/taskmill")          # or Broker(None) for in-memory
    broker.enqueue("email", "send", {"to": "a@example.org"}, idempotency_key="order-17")
    with WorkerPool(broker, registry, concurrency=8):
        ...

See README.md and docs/ for the design, the WAL format and the semantics of
leases, retries and idempotency keys.
"""

from .backoff import Backoff, parse_backoff
from .broker import Broker, Enqueued, Reservation
from .clock import ManualClock, SystemClock
from .config import BrokerConfig, QueueConfig
from .errors import (BrokerClosed, InvalidKey, InvalidTransition, LeaseLost, PermanentError, Retry,
                     TaskmillError, UnknownJob, ValidationError, WalCorrupt)
from .events import Hooks
from .handlers import JobContext, Registry, default_registry
from .idempotency import normalize_key
from .metrics import Metrics
from .reaper import Reaper
from .runtime import Runtime
from .scheduler import Schedule, Scheduler
from .worker import WorkerPool, run_one

__all__ = [
    "Backoff", "Broker", "BrokerClosed", "BrokerConfig", "Enqueued", "Hooks", "InvalidKey",
    "InvalidTransition", "JobContext", "LeaseLost", "ManualClock", "Metrics", "PermanentError",
    "QueueConfig", "Reaper", "Registry", "Reservation", "Retry", "Runtime", "Schedule", "Scheduler",
    "SystemClock", "TaskmillError", "UnknownJob", "ValidationError", "WalCorrupt", "WorkerPool",
    "default_registry", "normalize_key", "parse_backoff", "run_one",
]

__version__ = "2.5.0"
