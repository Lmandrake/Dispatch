"""An issue's timeline: its audit events and comments merged in time order
(``trellis show KEY --timeline``).

Entries are ``(timestamp, kind, text)`` tuples with kind ``"event"`` or
``"comment"``.  Ties on timestamp keep events before comments and otherwise
preserve seq / id order.  The ``comment.added`` event itself is left out
because the comment is shown instead.
"""

from trellis.textutil import oneline


def describe_event(ev):
    d = ev.details
    a = ev.action
    if a == "issue.created":
        return f"{ev.actor} created the issue"
    if a == "issue.transitioned":
        return f"{ev.actor} moved it from {d.get('from')} to {d.get('to')}"
    if a == "issue.assigned":
        to = d.get("to") or "nobody"
        return f"{ev.actor} assigned it to {to}"
    if a == "issue.labeled":
        return f"{ev.actor} added label(s) {', '.join(d.get('added', []))}"
    if a == "issue.unlabeled":
        return f"{ev.actor} removed label(s) {', '.join(d.get('removed', []))}"
    if a == "issue.watched":
        return f"{d.get('username')} started watching"
    if a == "issue.unwatched":
        return f"{d.get('username')} stopped watching"
    if a == "issue.updated":
        fields = ", ".join(sorted(d.get("changes", {})))
        return f"{ev.actor} changed {fields}"
    return f"{ev.actor} {a}"


def timeline(tracker, key):
    issue = tracker.issue(key)
    entries = []
    for ev in tracker.audit.events(subject=issue.key):
        if ev.action == "comment.added":
            continue
        entries.append((ev.timestamp, 0, ev.seq, "event", describe_event(ev)))
    for c in tracker.comments(issue.key):
        entries.append((c.created_at, 1, c.id, "comment",
                        f"{c.author or 'system'} commented: {oneline(c.body, 60)}"))
    entries.sort(key=lambda e: (e[0], e[1], e[2]))
    return [(ts, kind, text) for ts, _, _, kind, text in entries]


def render_timeline(entries):
    return "".join(f"{ts}  {text}\n" for ts, _, text in entries)
