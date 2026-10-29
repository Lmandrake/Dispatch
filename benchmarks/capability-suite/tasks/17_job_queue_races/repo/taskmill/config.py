"""Broker configuration.

A :class:`BrokerConfig` is a plain dataclass; every component reads the
fields it needs from it. ``BrokerConfig.from_dict`` accepts the JSON layout
used by ``taskmill.json`` files (see docs/CONFIG.md) and rejects unknown keys,
so typos fail loudly instead of being ignored.

Per-queue overrides live in ``queues``: a mapping from queue name to a
:class:`QueueConfig`. A queue that is not listed uses the broker defaults.
"""

import json
import os
import re
from dataclasses import asdict, dataclass, field, fields, replace
from typing import Dict, Optional

from .errors import ConfigError

QUEUE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,63}$")

FSYNC_MODES = ("always", "batch", "never")


def check_queue_name(name: str) -> str:
    if not isinstance(name, str) or not QUEUE_NAME_RE.match(name):
        raise ConfigError(
            f"bad queue name {name!r}: use 1-64 of a-z 0-9 _ . : - (starting with a letter or digit)")
    return name


@dataclass
class QueueConfig:
    """Overrides for one queue. ``None`` means: use the broker default."""

    max_attempts: Optional[int] = None
    visibility_timeout: Optional[float] = None
    backoff: Optional[dict] = None
    rate: Optional[float] = None       # reservations per second (token bucket), None = unlimited
    burst: int = 1                     # bucket size when rate is set
    paused: bool = False               # initial paused state
    fair: bool = False                 # weighted round robin across tenants (docs/FAIRNESS.md)
    tenant_weights: Optional[dict] = None
    default_weight: int = 1

    def validate(self, name: str) -> None:
        if self.max_attempts is not None and (not isinstance(self.max_attempts, int) or self.max_attempts < 1):
            raise ConfigError(f"queue {name}: max_attempts must be a positive integer")
        if self.visibility_timeout is not None and not (self.visibility_timeout > 0):
            raise ConfigError(f"queue {name}: visibility_timeout must be > 0")
        if self.rate is not None and not (self.rate > 0):
            raise ConfigError(f"queue {name}: rate must be > 0")
        if not isinstance(self.burst, int) or self.burst < 1:
            raise ConfigError(f"queue {name}: burst must be a positive integer")
        if self.backoff is not None:
            from .backoff import parse_backoff
            parse_backoff(self.backoff)
        if not isinstance(self.default_weight, int) or isinstance(self.default_weight, bool) \
                or self.default_weight < 1:
            raise ConfigError(f"queue {name}: default_weight must be a positive integer")
        for tenant, w in (self.tenant_weights or {}).items():
            if not isinstance(w, int) or isinstance(w, bool) or w < 1:
                raise ConfigError(f"queue {name}: weight for tenant {tenant} must be a positive integer")


DEFAULT_BACKOFF = {"kind": "exponential", "base": 1.0, "factor": 2.0, "max": 300.0, "jitter": "none"}


@dataclass
class BrokerConfig:
    id_prefix: str = "job"
    visibility_timeout: float = 30.0       # seconds a reservation lasts without a heartbeat
    max_visibility_timeout: float = 3600.0
    max_attempts: int = 5                  # deliveries before a failing job is dead
    backoff: dict = field(default_factory=lambda: dict(DEFAULT_BACKOFF))
    default_priority: int = 5
    dedup_window: float = 86400.0          # idempotency keys live this long after the job finishes
    retention: float = 7 * 86400.0         # finished jobs are purged this long after finishing
    max_payload_bytes: int = 64 * 1024
    max_result_bytes: int = 64 * 1024
    max_errors_kept: int = 5
    retired_token_ttl: float = 600.0       # how long an expired lease's token is remembered
    wal_fsync: str = "always"
    wal_segment_bytes: int = 1 << 20
    checkpoint_every: int = 0              # records between automatic checkpoints, 0 = never
    snapshots_kept: int = 2
    queues: Dict[str, QueueConfig] = field(default_factory=dict)

    # ---------------------------------------------------------------- checks

    def validate(self) -> "BrokerConfig":
        if not re.match(r"^[a-z][a-z0-9_]*$", self.id_prefix or ""):
            raise ConfigError("id_prefix must match [a-z][a-z0-9_]*")
        if not (self.visibility_timeout > 0):
            raise ConfigError("visibility_timeout must be > 0")
        if self.max_visibility_timeout < self.visibility_timeout:
            raise ConfigError("max_visibility_timeout must be >= visibility_timeout")
        if not isinstance(self.max_attempts, int) or self.max_attempts < 1:
            raise ConfigError("max_attempts must be a positive integer")
        if not isinstance(self.default_priority, int) or not 0 <= self.default_priority <= 9:
            raise ConfigError("default_priority must be an integer 0-9")
        for name in ("dedup_window", "retention", "retired_token_ttl"):
            if getattr(self, name) < 0:
                raise ConfigError(f"{name} must be >= 0")
        for name in ("max_payload_bytes", "max_result_bytes", "wal_segment_bytes"):
            if not isinstance(getattr(self, name), int) or getattr(self, name) < 64:
                raise ConfigError(f"{name} must be an integer >= 64")
        if not isinstance(self.max_errors_kept, int) or self.max_errors_kept < 0:
            raise ConfigError("max_errors_kept must be a non-negative integer")
        if self.wal_fsync not in FSYNC_MODES:
            raise ConfigError(f"wal_fsync must be one of {', '.join(FSYNC_MODES)}")
        if not isinstance(self.checkpoint_every, int) or self.checkpoint_every < 0:
            raise ConfigError("checkpoint_every must be a non-negative integer")
        if not isinstance(self.snapshots_kept, int) or self.snapshots_kept < 1:
            raise ConfigError("snapshots_kept must be a positive integer")
        from .backoff import parse_backoff
        parse_backoff(self.backoff)
        for name, qc in self.queues.items():
            check_queue_name(name)
            qc.validate(name)
        return self

    # ------------------------------------------------------------ per queue

    def queue(self, name: str) -> QueueConfig:
        return self.queues.get(name) or QueueConfig()

    def max_attempts_for(self, queue: str) -> int:
        qc = self.queues.get(queue)
        return qc.max_attempts if qc and qc.max_attempts is not None else self.max_attempts

    def visibility_timeout_for(self, queue: str) -> float:
        qc = self.queues.get(queue)
        return qc.visibility_timeout if qc and qc.visibility_timeout is not None else self.visibility_timeout

    def backoff_for(self, queue: str) -> dict:
        qc = self.queues.get(queue)
        return dict(qc.backoff) if qc and qc.backoff is not None else dict(self.backoff)

    # ------------------------------------------------------------ (de)serialise

    def to_dict(self) -> dict:
        d = asdict(self)
        d["queues"] = {k: {kk: vv for kk, vv in asdict(v).items() if vv is not None}
                       for k, v in self.queues.items()}
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "BrokerConfig":
        if not isinstance(data, dict):
            raise ConfigError("configuration must be a JSON object")
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(data) - known)
        if unknown:
            raise ConfigError(f"unknown configuration key(s): {', '.join(unknown)}")
        kw = dict(data)
        queues = {}
        qknown = {f.name for f in fields(QueueConfig)}
        for name, qd in (kw.pop("queues", None) or {}).items():
            if not isinstance(qd, dict):
                raise ConfigError(f"queue {name}: expected an object")
            bad = sorted(set(qd) - qknown)
            if bad:
                raise ConfigError(f"queue {name}: unknown key(s): {', '.join(bad)}")
            queues[name] = QueueConfig(**qd)
        cfg = cls(**kw, queues=queues)
        for name in ("visibility_timeout", "max_visibility_timeout", "dedup_window", "retention",
                     "retired_token_ttl"):
            v = getattr(cfg, name)
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ConfigError(f"{name} must be a number")
            setattr(cfg, name, float(v))
        return cfg.validate()

    @classmethod
    def from_file(cls, path: str) -> "BrokerConfig":
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except OSError as exc:
            raise ConfigError(f"cannot read {path}: {exc.strerror}") from exc
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{path}: invalid JSON ({exc.msg} at line {exc.lineno})") from exc
        return cls.from_dict(data)

    @classmethod
    def from_env(cls, environ=None, base: "BrokerConfig" = None) -> "BrokerConfig":
        """Apply ``TASKMILL_<FIELD>`` overrides (numbers and strings only) to ``base``."""
        environ = os.environ if environ is None else environ
        cfg = replace(base) if base is not None else cls()
        for f in fields(cls):
            if f.name in ("queues", "backoff"):
                continue
            raw = environ.get("TASKMILL_" + f.name.upper())
            if raw is None:
                continue
            current = getattr(cfg, f.name)
            try:
                if isinstance(current, bool):
                    value = raw.lower() in ("1", "true", "yes", "on")
                elif isinstance(current, int):
                    value = int(raw)
                elif isinstance(current, float):
                    value = float(raw)
                else:
                    value = raw
            except ValueError as exc:
                raise ConfigError(f"TASKMILL_{f.name.upper()}: {raw!r} is not a valid {type(current).__name__}") from exc
            setattr(cfg, f.name, value)
        return cfg.validate()

    def with_overrides(self, **kw) -> "BrokerConfig":
        return replace(self, **kw).validate()
