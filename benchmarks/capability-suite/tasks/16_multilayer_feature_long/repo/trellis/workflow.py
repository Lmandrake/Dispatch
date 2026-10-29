"""Issue status workflow.

Allowed transitions (anything else raises ``ValidationError``)::

    open         -> in_progress, blocked, done, wontfix
    in_progress  -> open, review, blocked, done, wontfix
    review       -> in_progress, done, wontfix
    blocked      -> open, in_progress, wontfix
    done         -> open                      (reopen)
    wontfix      -> open                      (reopen)

Entering ``done`` or ``wontfix`` stamps ``closed_at``; reopening clears it.
A transition to the issue's current status is an error, not a no-op.
"""

from trellis.errors import ValidationError
from trellis.models import CLOSED_STATUSES

TRANSITIONS = {
    "open": ("in_progress", "blocked", "done", "wontfix"),
    "in_progress": ("open", "review", "blocked", "done", "wontfix"),
    "review": ("in_progress", "done", "wontfix"),
    "blocked": ("open", "in_progress", "wontfix"),
    "done": ("open",),
    "wontfix": ("open",),
}


def allowed_targets(status):
    return TRANSITIONS.get(status, ())


def check_transition(current, target):
    if current == target:
        raise ValidationError(f"issue is already {target}")
    if target not in allowed_targets(current):
        allowed = ", ".join(allowed_targets(current)) or "nothing"
        raise ValidationError(f"cannot move from {current} to {target} (allowed: {allowed})")


def closes(target):
    return target in CLOSED_STATUSES
