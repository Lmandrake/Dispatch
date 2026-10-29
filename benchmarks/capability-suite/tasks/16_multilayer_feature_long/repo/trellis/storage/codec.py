"""Conversion between model objects and plain dicts.

The JSON backend stores these dicts directly; the SQLite backend uses them
for the scalar columns and keeps ``labels`` / ``watchers`` in side tables.
Keeping one codec means both backends agree on defaults and types.

Key order in the dicts is the on-disk key order of the JSON format and must
not change between releases without a format-version bump.
"""

from trellis.errors import StorageError
from trellis.models import AuditEvent, Comment, Issue, Membership, Project, User


def _bad(kind, d, exc):
    return StorageError(f"bad {kind} record {d!r}: {exc}")


# ---- users -------------------------------------------------------------------

def user_to_dict(u):
    return {
        "username": u.username,
        "display_name": u.display_name,
        "email": u.email,
        "active": u.active,
        "created_at": u.created_at,
    }


def user_from_dict(d):
    try:
        return User(
            username=d["username"],
            display_name=d.get("display_name") or d["username"],
            email=d.get("email") or "",
            active=bool(d.get("active", True)),
            created_at=d.get("created_at") or "",
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise _bad("user", d, exc) from None


# ---- projects ----------------------------------------------------------------

def project_to_dict(p):
    return {
        "key": p.key,
        "name": p.name,
        "description": p.description,
        "lead": p.lead,
        "archived": p.archived,
        "next_number": p.next_number,
        "created_at": p.created_at,
    }


def project_from_dict(d):
    try:
        return Project(
            key=d["key"],
            name=d["name"],
            description=d.get("description") or "",
            lead=d.get("lead") or "",
            archived=bool(d.get("archived", False)),
            next_number=int(d.get("next_number", 1)),
            created_at=d.get("created_at") or "",
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise _bad("project", d, exc) from None


# ---- memberships -------------------------------------------------------------

def membership_to_dict(m):
    return {"project": m.project, "username": m.username, "role": m.role}


def membership_from_dict(d):
    try:
        return Membership(project=d["project"], username=d["username"], role=d["role"])
    except (KeyError, TypeError) as exc:
        raise _bad("membership", d, exc) from None


# ---- issues ------------------------------------------------------------------

ISSUE_SCALARS = (
    "project", "number", "title", "description", "type", "status", "priority",
    "reporter", "assignee", "due", "estimate", "created_at", "updated_at", "closed_at",
)


def issue_to_dict(i):
    return {
        "project": i.project,
        "number": i.number,
        "title": i.title,
        "description": i.description,
        "type": i.type,
        "status": i.status,
        "priority": i.priority,
        "reporter": i.reporter,
        "assignee": i.assignee,
        "labels": list(i.labels),
        "watchers": list(i.watchers),
        "due": i.due,
        "estimate": i.estimate,
        "created_at": i.created_at,
        "updated_at": i.updated_at,
        "closed_at": i.closed_at,
    }


def issue_from_dict(d, labels=None, watchers=None):
    """Build an Issue.  ``labels`` / ``watchers`` override the dict's own
    lists (the SQLite backend passes them in from its side tables)."""
    try:
        est = d.get("estimate")
        return Issue(
            project=d["project"],
            number=int(d["number"]),
            title=d["title"],
            description=d.get("description") or "",
            type=d.get("type") or "task",
            status=d.get("status") or "open",
            priority=d.get("priority") or "normal",
            reporter=d.get("reporter") or "",
            assignee=d.get("assignee") or "",
            labels=tuple(sorted(set(labels if labels is not None else d.get("labels") or ()))),
            watchers=tuple(sorted(set(watchers if watchers is not None else d.get("watchers") or ()))),
            due=d.get("due") or "",
            estimate=None if est is None else int(est),
            created_at=d.get("created_at") or "",
            updated_at=d.get("updated_at") or "",
            closed_at=d.get("closed_at") or "",
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise _bad("issue", d, exc) from None


# ---- comments ----------------------------------------------------------------

def comment_to_dict(c):
    return {"id": c.id, "issue": c.issue, "author": c.author, "body": c.body,
            "created_at": c.created_at}


def comment_from_dict(d):
    try:
        return Comment(id=int(d["id"]), issue=d["issue"], author=d.get("author") or "",
                       body=d.get("body") or "", created_at=d.get("created_at") or "")
    except (KeyError, TypeError, ValueError) as exc:
        raise _bad("comment", d, exc) from None


# ---- events ------------------------------------------------------------------

def event_to_dict(e):
    return {
        "seq": e.seq,
        "timestamp": e.timestamp,
        "actor": e.actor,
        "action": e.action,
        "subject": e.subject,
        "details": e.details,
    }


def event_from_dict(d):
    try:
        return AuditEvent(
            seq=int(d["seq"]),
            timestamp=d["timestamp"],
            actor=d.get("actor") or "system",
            action=d["action"],
            subject=d["subject"],
            details=dict(d.get("details") or {}),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise _bad("event", d, exc) from None
