"""The audit trail.

Every successful mutating service call records exactly one AuditEvent per
logical change through ``AuditLog.record``.  Events live in the repository
(so the JSON backend persists them alongside the data) and are numbered
consecutively from 1.

Actions currently recorded, with their ``details`` keys:

==================  ===========================================
action              details
==================  ===========================================
item.added          name, quantity, price_cents, location
item.updated        changes: {field: [old, new], ...}
item.removed        name
stock.received      quantity, new_quantity, note
stock.adjusted      delta, new_quantity, reason
order.placed        sku, quantity, customer
order.fulfilled     sku, quantity, new_quantity
order.cancelled     sku, quantity, reason
==================  ===========================================
"""

from stockroom.clock import utc_now
from stockroom.models import AuditEvent


class AuditLog:
    def __init__(self, repo, clock=utc_now):
        self.repo = repo
        self.clock = clock

    def record(self, action, subject, **details):
        seq = self.repo.last_event_seq() + 1
        event = AuditEvent(seq=seq, timestamp=self.clock(), action=action,
                           subject=subject, details=details)
        self.repo.append_event(event)
        return event

    def events(self, subject=None, action=None, since_seq=0):
        """Events filtered by exact subject, by action (exact, or a prefix
        ending in ``.`` such as ``"order."``), and by ``seq > since_seq``."""
        out = []
        for ev in self.repo.list_events():
            if ev.seq <= since_seq:
                continue
            if subject is not None and ev.subject != subject:
                continue
            if action is not None:
                if action.endswith("."):
                    if not ev.action.startswith(action):
                        continue
                elif ev.action != action:
                    continue
            out.append(ev)
        return out


def format_event(event):
    """One-line human rendering used by ``stockroom history``."""
    parts = []
    for key in sorted(event.details):
        value = event.details[key]
        if isinstance(value, dict):
            inner = ", ".join(f"{k}: {v[0]!r} -> {v[1]!r}" if isinstance(v, (list, tuple)) and len(v) == 2
                              else f"{k}: {v!r}" for k, v in sorted(value.items()))
            parts.append(f"{key}={{{inner}}}")
        else:
            parts.append(f"{key}={value!r}")
    tail = (" " + " ".join(parts)) if parts else ""
    return f"#{event.seq} {event.timestamp} {event.action} {event.subject}{tail}"
