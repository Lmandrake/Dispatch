"""Fault injection for game-day drills.

A :class:`Chaos` harness attaches faults to broker hook points (see
``taskmill.events.POINTS``). Each :class:`Fault` names a point, a probability
and an action: raise an exception from the hook (which abandons the operation
in progress exactly as any other error would) or delay the calling thread.
Decisions come from a generator seeded per harness, so a drill replays
identically for the same seed and the same sequence of hook firings.

    chaos = Chaos(broker, seed=7)
    chaos.fail("ack.before_commit", probability=0.2)
    chaos.delay("heartbeat", seconds=0.5, probability=1.0)
    with chaos:
        run_the_drill()
    print(chaos.render())

Faults can be limited (``limit`` injections), restricted to a predicate on
the hook arguments (``when``), and switched off individually. The harness
counts firings and injections per fault. Leaving the ``with`` block (or
``stop()``) removes every hook it installed.
"""

import random
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .errors import TaskmillError
from .events import POINTS


class InjectedFault(TaskmillError):
    """The default exception raised by a ``fail`` fault."""


@dataclass
class Fault:
    name: str
    point: str
    probability: float = 1.0
    action: str = "raise"
    exception: Callable[[], BaseException] = lambda: InjectedFault("injected fault")
    seconds: float = 0.0
    limit: Optional[int] = None
    when: Optional[Callable[[dict], bool]] = None
    enabled: bool = True
    seen: int = 0
    injected: int = 0

    def exhausted(self) -> bool:
        return self.limit is not None and self.injected >= self.limit

    def to_dict(self) -> dict:
        return {"name": self.name, "point": self.point, "action": self.action,
                "probability": self.probability, "seen": self.seen, "injected": self.injected,
                "enabled": self.enabled}


class Chaos:
    def __init__(self, broker, seed: int = 0, sleep: Callable[[float], None] = time.sleep):
        self.broker = broker
        self.sleep = sleep
        self._rng = random.Random(seed)
        self._lock = threading.Lock()
        self._faults: Dict[str, Fault] = {}
        self._removers: List[Callable[[], None]] = []
        self._installed: Dict[str, Callable[[], None]] = {}
        self._active = False

    # ------------------------------------------------------------ defining faults

    def add(self, fault: Fault) -> Fault:
        if fault.point not in POINTS:
            raise ValueError(f"unknown hook point {fault.point!r}")
        if not 0.0 <= fault.probability <= 1.0:
            raise ValueError("probability must be between 0 and 1")
        if fault.action not in ("raise", "delay"):
            raise ValueError("action must be 'raise' or 'delay'")
        with self._lock:
            if fault.name in self._faults:
                raise ValueError(f"duplicate fault {fault.name}")
            self._faults[fault.name] = fault
            if self._active:
                self._hook(fault.point)
        return fault

    def fail(self, point: str, probability: float = 1.0, exception: Optional[Callable] = None,
             limit: Optional[int] = None, when: Optional[Callable[[dict], bool]] = None,
             name: Optional[str] = None) -> Fault:
        fault = Fault(name or f"fail:{point}:{len(self._faults)}", point, probability, "raise",
                      limit=limit, when=when)
        if exception is not None:
            fault.exception = exception
        return self.add(fault)

    def delay(self, point: str, seconds: float, probability: float = 1.0, limit: Optional[int] = None,
              when: Optional[Callable[[dict], bool]] = None, name: Optional[str] = None) -> Fault:
        return self.add(Fault(name or f"delay:{point}:{len(self._faults)}", point, probability, "delay",
                              seconds=seconds, limit=limit, when=when))

    def disable(self, name: str) -> None:
        self._faults[name].enabled = False

    def enable(self, name: str) -> None:
        self._faults[name].enabled = True

    # ------------------------------------------------------------ install / remove

    def _hook(self, point: str) -> None:
        if point not in self._installed:
            self._installed[point] = self.broker.hooks.add(point, lambda **kw: self._fire(point, kw))

    def start(self) -> "Chaos":
        with self._lock:
            if not self._active:
                self._active = True
                for point in sorted({f.point for f in self._faults.values()}):
                    self._hook(point)
        return self

    def stop(self) -> None:
        with self._lock:
            self._active = False
            removers, self._installed = list(self._installed.values()), {}
        for remove in removers:
            remove()

    def __enter__(self) -> "Chaos":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    # ------------------------------------------------------------ firing

    def _fire(self, point: str, kw: dict) -> None:
        pause = 0.0
        error = None
        with self._lock:
            for fault in self._faults.values():
                if fault.point != point or not fault.enabled or fault.exhausted():
                    continue
                if fault.when is not None and not fault.when(kw):
                    continue
                fault.seen += 1
                if self._rng.random() >= fault.probability:
                    continue
                fault.injected += 1
                if fault.action == "delay":
                    pause += fault.seconds
                elif error is None:
                    error = fault.exception()
        if pause:
            self.sleep(pause)
        if error is not None:
            raise error

    # ------------------------------------------------------------ reporting

    def stats(self) -> Dict[str, dict]:
        with self._lock:
            return {name: f.to_dict() for name, f in sorted(self._faults.items())}

    def total_injected(self) -> int:
        with self._lock:
            return sum(f.injected for f in self._faults.values())

    def render(self) -> str:
        rows = self.stats().values()
        if not rows:
            return "chaos: no faults defined\n"
        lines = ["chaos drill report"]
        for r in rows:
            state = "" if r["enabled"] else " (disabled)"
            lines.append(f"  {r['name']:<28} {r['action']:<5} p={r['probability']:.2f} "
                         f"{r['injected']}/{r['seen']} injected{state}")
        return "\n".join(lines) + "\n"
