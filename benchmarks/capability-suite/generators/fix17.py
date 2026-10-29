"""Apply the reference fixes for task 17 to a copy of repo/ (argv[1])."""
import os, sys
ROOT = sys.argv[1]

def sub(rel, old, new, n=1):
    p = os.path.join(ROOT, rel)
    s = open(p).read()
    assert s.count(old) == n, (rel, old[:70], s.count(old))
    open(p, 'w').write(s.replace(old, new))

# 1 ack/nack decide at commit
sub('taskmill/broker.py', '''            now = self.clock()
            job = self._job_locked(job_id)
            self._commit_locked(out, "ack",''', '''            now = self.clock()
            try:
                self.state.leases.resolve(token, now)
            except LeaseLost as exc:
                raise self._lost("ack", exc)
            job = self._job_locked(job_id)
            self._commit_locked(out, "ack",''')
sub('taskmill/broker.py', '''            now = self.clock()
            job = self._job_locked(job_id)
            if permanent''', '''            now = self.clock()
            try:
                self.state.leases.resolve(token, now)
            except LeaseLost as exc:
                raise self._lost("nack", exc)
            job = self._job_locked(job_id)
            if permanent''')
# 2 heartbeat ownership
sub('taskmill/leases.py', '''        lease = self._by_job.get(job_id)
        if lease is None:
            raise self._lost(token, now)
        if now >= lease.deadline:
            raise LeaseLost(f"{job_id}: lease expired at {lease.deadline:.3f}")
        deadline = min''', '''        lease = self._by_job.get(job_id)
        if lease is None or lease.token != token:
            raise self._lost(token, now)
        if now >= lease.deadline:
            raise LeaseLost(f"{job_id}: lease expired at {lease.deadline:.3f}")
        deadline = min''')
# 3 idempotency canonical form
sub('taskmill/idempotency.py', '_FORM = "NFKC"', '_FORM = "NFC"')
sub('taskmill/idempotency.py', '    return _compact(text)', '    return text')
# 4 replay in seq order
sub('taskmill/recovery.py', '''    replayed = skipped = 0
    for rec in records:''', '''    replayed = skipped = 0
    for rec in sorted(records, key=lambda r: r["seq"]):''')
# 5 truncate torn tail
sub('taskmill/wal.py', '''                newest = result.segments[-1]
                self._current = newest''', '''                newest = result.segments[-1]
                if result.torn is not None and result.torn.path == newest.path:
                    with open(newest.path, "r+b") as fh:
                        fh.truncate(result.torn.offset)
                        fh.flush()
                        os.fsync(fh.fileno())
                    newest.size = result.torn.offset
                self._current = newest''')
# 6 exact metrics
sub('taskmill/metrics.py', '''        key = _label_key(labels)
        value = self._values.get(key, 0) + n
        self._updated[key] = self._clock()
        self._values[key] = value''', '''        key = _label_key(labels)
        now = self._clock()
        with self._lock:
            self._values[key] = self._values.get(key, 0) + n
            self._updated[key] = now''')
sub('taskmill/metrics.py', '''    def get(self, **labels) -> float:
        return self._values.get(_label_key(labels), 0)''', '''    def get(self, **labels) -> float:
        with self._lock:
            return self._values.get(_label_key(labels), 0)''')
sub('taskmill/metrics.py', '''    def last_updated(self, **labels) -> Optional[float]:
        return self._updated.get(_label_key(labels))''', '''    def last_updated(self, **labels) -> Optional[float]:
        with self._lock:
            return self._updated.get(_label_key(labels))''')
sub('taskmill/metrics.py', '''        count = self._count + 1
        total = self._sum + value
        self._updated = self._clock()
        self._count = count
        self._sum = total
        if value > self._max:
            self._max = value
        for i, bound in enumerate(self.buckets):
            if value <= bound:
                self._bucket_counts[i] += 1''', '''        now = self._clock()
        with self._lock:
            self._updated = now
            self._count += 1
            self._sum += value
            if value > self._max:
                self._max = value
            for i, bound in enumerate(self.buckets):
                if value <= bound:
                    self._bucket_counts[i] += 1''')
# 7 promotion
sub('taskmill/pqueue.py', '''        self._clean_top(self._ready)
        if not self._ready:
            self.promote_due(now)
            self._clean_top(self._ready)
        if not self._ready:''', '''        self.promote_due(now)
        self._clean_top(self._ready)
        if not self._ready:''')
sub('taskmill/pqueue.py', '''            job.state = PENDING
            job.ready_at = now''', '''            job.state = PENDING
            job.ready_at = job.run_at''')
# 8 cron leap years
sub('taskmill/cron.py', '''        return 29 if year % 4 == 0 else 28''', '''        return 29 if calendar.isleap(year) else 28''')
# 9 decorrelated cap
sub('taskmill/backoff.py', '''            prev = rng.uniform(self.base, max(self.base, prev * 3))
        return prev''', '''            prev = rng.uniform(self.base, max(self.base, prev * 3))
            if self.max is not None:
                prev = min(prev, self.max)
        return prev''')
# 10 cancel decides at commit
sub('taskmill/broker.py', '''            job = self._job_locked(job_id)
            self._commit_locked(out, "cancel", id=job_id, at=self.clock(), **{"from": state})''', '''            job = self._job_locked(job_id)
            if job.state in FINISHED:
                return False
            self._commit_locked(out, "cancel", id=job_id, at=self.clock(), **{"from": job.state})''')
# 11 checkpoint position captured with the state
sub('taskmill/broker.py', '''            next_id = self.state.next_id
            self._since_checkpoint = 0''', '''            next_id = self.state.next_id
            last_seq = self._seq
            self._since_checkpoint = 0''')
sub('taskmill/broker.py', '''snap = snapmod.Snapshot(last_seq=self.last_seq,''', '''snap = snapmod.Snapshot(last_seq=last_seq,''')
# 12 pool gives back prefetched jobs
sub('taskmill/worker.py', '''        self._untrack(buffered)

    def _untrack(self, reservations) -> None:''', '''        for res in buffered:
            try:
                self.broker.release(res.token)
            except (LeaseLost, BrokerClosed):
                pass
        self._untrack(buffered)

    def _untrack(self, reservations) -> None:''')
# 13 expiry on last attempt
sub('taskmill/broker.py', '''            to = FAILED if job.attempts_left < 0 else PENDING''', '''            to = FAILED if job.attempts_left <= 0 else PENDING''')
# 14 result cache tenant
sub('taskmill/resultcache.py', '''    body = codec.encode({"q": queue, "k": kind, "p": payload})''', '''    body = codec.encode({"q": queue, "k": kind, "p": payload, "t": tenant})''')
print("fixes applied")
