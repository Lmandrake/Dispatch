"""The per-user digest.

A digest for user U, built at "today" T with cursor C (the last event seq U
has already seen), has these sections, in this order.  Empty sections are
left out of the rendered text.

Overdue
    open issues assigned to U whose due date is before T, in
    (due, project, number) order.
Due soon
    open issues assigned to U due on T or within the next ``SOON_DAYS``
    days, same order.
Watching
    events with seq > C on issues U watches, made by someone other than U,
    in seq order; at most ``MAX_ACTIVITY`` (the newest ones), with a
    "... and N more" line when cut.
Mentions
    ``comment.added`` events with seq > C whose ``mentions`` include U,
    in seq order.

Only issues of projects U can currently read are included.  U must be an
active user.  ``Digest.last_seq`` is the highest event seq at build time;
the CLI stores it as the new cursor when asked to (``digest --mark``).

Rendered form::

    Digest for ana (2026-05-01)

    Overdue (1)
      WEB-3  due 2026-04-28 (3d ago)  Login page broken

    Due soon (2)
      WEB-7  due 2026-05-01 (today)  Ship it
      OPS-2  due 2026-05-04 (in 3d)  Rotate keys

    Watching (1)
      #41 bob issue.transitioned WEB-7 from='open' to='in_progress'

    Mentions (1)
      #44 bob WEB-9: comment 12

With nothing to report the whole digest is the header line followed by
``Nothing new.``.
"""

from dataclasses import dataclass, field

from trellis.dates import days_until
from trellis.errors import PermissionDenied
from trellis.table import truncate

SOON_DAYS = 7
MAX_ACTIVITY = 20


@dataclass
class Digest:
    username: str
    today: str
    overdue: list = field(default_factory=list)
    due_soon: list = field(default_factory=list)
    activity: list = field(default_factory=list)
    activity_dropped: int = 0
    mentions: list = field(default_factory=list)
    last_seq: int = 0

    @property
    def empty(self):
        return not (self.overdue or self.due_soon or self.activity or self.mentions)


def build_digest(tracker, username, since_seq=0):
    user = tracker.repo.get_user(username)
    if user is None or not user.active:
        raise PermissionDenied(f"no digest for {username}: not an active user")
    reader = tracker.as_user(username)
    today = reader.today()
    readable = {p.key for p in reader.visible_projects()}
    d = Digest(username=username, today=today, last_seq=tracker.repo.last_event_seq())

    for issue, days in reader.agenda(days=SOON_DAYS, username=username):
        (d.overdue if days < 0 else d.due_soon).append((issue, days))

    watched = {i.key for i in tracker.repo.list_issues()
               if username in i.watchers and i.project in readable}
    activity = []
    for ev in tracker.repo.list_events():
        if ev.seq <= since_seq:
            continue
        if ev.action.startswith(("issue.", "comment.")) and ev.subject.rpartition("-")[0] in readable:
            if ev.action == "comment.added" and username in ev.details.get("mentions", ()):
                d.mentions.append(ev)
            elif ev.subject in watched and ev.actor != username:
                activity.append(ev)
    if len(activity) > MAX_ACTIVITY:
        d.activity_dropped = len(activity) - MAX_ACTIVITY
        activity = activity[-MAX_ACTIVITY:]
    d.activity = activity
    return d


def _when(days):
    if days == 0:
        return "today"
    if days < 0:
        return f"{-days}d ago"
    return f"in {days}d"


def _issue_lines(items):
    width = max(len(i.key) for i, _ in items)
    return [f"  {i.key.ljust(width)}  due {i.due} ({_when(d)})  {truncate(i.title, 50)}"
            for i, d in items]


def _event_line(ev):
    from trellis.audit import format_event
    text = format_event(ev)
    # drop the timestamp: "#41 2026-...Z bob ..." -> "#41 bob ..."
    seq, _, rest = text.partition(" ")
    _, _, rest = rest.partition(" ")
    return f"  {seq} {rest}"


def render_digest(d):
    lines = [f"Digest for {d.username} ({d.today})", ""]
    if d.empty:
        lines.append("Nothing new.")
        return "\n".join(lines) + "\n"
    if d.overdue:
        lines.append(f"Overdue ({len(d.overdue)})")
        lines.extend(_issue_lines(d.overdue))
        lines.append("")
    if d.due_soon:
        lines.append(f"Due soon ({len(d.due_soon)})")
        lines.extend(_issue_lines(d.due_soon))
        lines.append("")
    if d.activity:
        lines.append(f"Watching ({len(d.activity) + d.activity_dropped})")
        lines.extend(_event_line(ev) for ev in d.activity)
        if d.activity_dropped:
            lines.append(f"  ... and {d.activity_dropped} more")
        lines.append("")
    if d.mentions:
        lines.append(f"Mentions ({len(d.mentions)})")
        lines.extend(f"  #{ev.seq} {ev.actor} {ev.subject}: comment {ev.details.get('id')}"
                     for ev in d.mentions)
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def days_left(issue, today):
    return days_until(issue.due, today)
