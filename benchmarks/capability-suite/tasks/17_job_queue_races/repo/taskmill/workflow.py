"""Workflows: chains and fan-out/fan-in groups built on ordinary jobs.

A workflow is a small DAG of steps. Each step becomes a normal job when all
of its dependencies are done; a step whose dependency failed or was
cancelled is itself marked ``skipped`` (it never becomes a job). The
workflow is ``done`` when every step is done, ``failed`` as soon as a step
fails for good, and ``running`` otherwise.

    wf = Workflow("nightly")
    extract = wf.step("extract", "q", "extract", {"day": "2026-10-21"})
    a = wf.step("load-a", "q", "load", {"table": "a"}, after=[extract])
    b = wf.step("load-b", "q", "load", {"table": "b"}, after=[extract])
    wf.step("report", "q", "report", None, after=[a, b])
    runner = WorkflowRunner(broker)
    run_id = runner.start(wf)
    runner.advance(run_id)          # call after jobs finish (or let attach() do it)

Steps are enqueued with idempotency keys ``wf/<run id>/<step>``, so calling
``advance`` twice (or from two threads) never enqueues a step twice.

Workflow runs are kept in memory by the runner; they are not part of the
broker's WAL. After a restart, ``WorkflowRunner.resume(run_id, wf, job_ids)``
rebuilds a run from the job ids recorded by the caller.
"""

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .errors import ValidationError

STEP_WAITING = "waiting"
STEP_ENQUEUED = "enqueued"
STEP_DONE = "done"
STEP_FAILED = "failed"
STEP_SKIPPED = "skipped"


@dataclass
class Step:
    name: str
    queue: str
    kind: str
    payload: Any = None
    after: List[str] = field(default_factory=list)
    priority: Optional[int] = None


class Workflow:
    def __init__(self, name: str):
        if not name or "/" in name:
            raise ValidationError("workflow name must be non-empty and contain no '/'")
        self.name = name
        self.steps: Dict[str, Step] = {}

    def step(self, name: str, queue: str, kind: str, payload: Any = None, after=None,
             priority: Optional[int] = None) -> str:
        if not name or "/" in name:
            raise ValidationError("step name must be non-empty and contain no '/'")
        if name in self.steps:
            raise ValidationError(f"duplicate step {name}")
        deps = [d if isinstance(d, str) else d.name for d in (after or [])]
        for d in deps:
            if d not in self.steps:
                raise ValidationError(f"step {name}: unknown dependency {d}")
        self.steps[name] = Step(name, queue, kind, payload, deps, priority)
        return name

    def roots(self) -> List[str]:
        return [s.name for s in self.steps.values() if not s.after]

    def topological(self) -> List[str]:
        # Steps can only depend on earlier steps, so insertion order is topological.
        return list(self.steps)

    def dependents(self, name: str) -> List[str]:
        return [s.name for s in self.steps.values() if name in s.after]


@dataclass
class Run:
    run_id: str
    workflow: Workflow
    steps: Dict[str, str] = field(default_factory=dict)      # step -> STEP_* state
    jobs: Dict[str, str] = field(default_factory=dict)       # step -> job id

    @property
    def state(self) -> str:
        states = set(self.steps.values())
        if STEP_FAILED in states:
            return "failed"
        if states <= {STEP_DONE}:
            return "done"
        if states <= {STEP_DONE, STEP_SKIPPED}:
            return "failed"
        return "running"

    def to_dict(self) -> Dict[str, Any]:
        return {"run_id": self.run_id, "workflow": self.workflow.name, "state": self.state,
                "steps": dict(self.steps), "jobs": dict(self.jobs)}


class WorkflowRunner:
    def __init__(self, broker):
        self.broker = broker
        self._lock = threading.Lock()
        self._runs: Dict[str, Run] = {}
        self._n = 0
        self._by_job: Dict[str, str] = {}
        self._detach = None

    def start(self, wf: Workflow, run_id: Optional[str] = None) -> str:
        if not wf.steps:
            raise ValidationError("workflow has no steps")
        with self._lock:
            self._n += 1
            run_id = run_id or f"{wf.name}-{self._n}"
            if run_id in self._runs:
                raise ValidationError(f"run {run_id} already exists")
            run = Run(run_id, wf, {s: STEP_WAITING for s in wf.steps})
            self._runs[run_id] = run
        self.advance(run_id)
        return run_id

    def resume(self, run_id: str, wf: Workflow, job_ids: Dict[str, str]) -> Run:
        with self._lock:
            run = Run(run_id, wf, {s: STEP_WAITING for s in wf.steps})
            for step, job_id in job_ids.items():
                run.steps[step] = STEP_ENQUEUED
                run.jobs[step] = job_id
                self._by_job[job_id] = run_id
            self._runs[run_id] = run
        self.advance(run_id)
        return run

    def run(self, run_id: str) -> Run:
        with self._lock:
            run = self._runs.get(run_id)
        if run is None:
            raise ValidationError(f"no run {run_id}")
        return run

    def runs(self) -> List[str]:
        with self._lock:
            return sorted(self._runs)

    def _refresh(self, run: Run) -> None:
        for step, job_id in run.jobs.items():
            if run.steps[step] != STEP_ENQUEUED:
                continue
            try:
                state = self.broker.get(job_id).state
            except Exception:  # noqa: BLE001 - purged: treat as failed
                state = "failed"
            if state == "done":
                run.steps[step] = STEP_DONE
            elif state in ("failed", "cancelled"):
                run.steps[step] = STEP_FAILED

    def advance(self, run_id: str) -> List[str]:
        """Enqueue every step whose dependencies are done. Returns newly enqueued steps."""
        run = self.run(run_id)
        started: List[str] = []
        with self._lock:
            self._refresh(run)
            changed = True
            while changed:
                changed = False
                for name in run.workflow.topological():
                    if run.steps[name] != STEP_WAITING:
                        continue
                    deps = [run.steps[d] for d in run.workflow.steps[name].after]
                    if any(d in (STEP_FAILED, STEP_SKIPPED) for d in deps):
                        run.steps[name] = STEP_SKIPPED
                        changed = True
                    elif all(d == STEP_DONE for d in deps):
                        step = run.workflow.steps[name]
                        res = self.broker.enqueue(step.queue, step.kind, step.payload, priority=step.priority,
                                                  idempotency_key=f"wf/{run_id}/{name}")
                        run.jobs[name] = res.job_id
                        run.steps[name] = STEP_ENQUEUED
                        self._by_job[res.job_id] = run_id
                        started.append(name)
                        changed = True
        return started

    def attach(self, pool) -> None:
        """Advance runs automatically whenever ``pool`` finishes one of their jobs."""
        def on_end(job_id, worker, ok):
            with self._lock:
                run_id = self._by_job.get(job_id)
            if run_id is not None:
                self.advance(run_id)
        self._detach = self.broker.hooks.add("handler.end", on_end)

    def detach(self) -> None:
        if self._detach is not None:
            self._detach()
            self._detach = None
