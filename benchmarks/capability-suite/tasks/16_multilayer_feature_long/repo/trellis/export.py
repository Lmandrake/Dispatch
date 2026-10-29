"""Exports: issues, comments and events as CSV, JSON or a text table.

Column order and JSON key order are part of the interface (scripts parse
them), so new columns are only ever appended.

Issues
------
CSV columns, in order::

    key,project,number,title,type,status,priority,assignee,reporter,
    labels,watchers,due,estimate,created,updated,closed

``labels`` and ``watchers`` are joined with ``;``; an empty estimate is an
empty cell.  JSON is a list of objects with these keys in this order:
``key, project, number, title, description, type, status, priority,
assignee, reporter, labels, watchers, due, estimate, created_at,
updated_at, closed_at`` (labels and watchers as lists, estimate null when
unset).  Note that JSON carries the description and CSV does not.

The text table has the columns ``Key, Type, Status, Pri, Assignee, Due,
Title`` (title cut to 50 characters, ``-`` for an empty assignee or due
date) followed by a blank line and a footer ``N issues (O open)``.

Comments: CSV ``id,issue,author,created,body``; JSON objects with those keys
(``created_at`` for the timestamp).

Events: CSV ``seq,timestamp,actor,action,subject,details`` where details is
compact JSON with sorted keys; JSON objects with the event's own keys.
"""

import csv
import io
import json

from trellis.errors import ValidationError
from trellis.table import render_table, truncate
from trellis.textutil import plural

ISSUE_CSV_COLUMNS = (
    "key", "project", "number", "title", "type", "status", "priority", "assignee", "reporter",
    "labels", "watchers", "due", "estimate", "created", "updated", "closed",
)

TITLE_WIDTH = 50


def _csv(rows, header):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue()


# ---- issues ------------------------------------------------------------------

def issue_csv_row(i):
    return [
        i.key, i.project, i.number, i.title, i.type, i.status, i.priority, i.assignee,
        i.reporter, ";".join(i.labels), ";".join(i.watchers), i.due,
        "" if i.estimate is None else i.estimate, i.created_at, i.updated_at, i.closed_at,
    ]


def issues_to_csv(issues):
    return _csv([issue_csv_row(i) for i in issues], ISSUE_CSV_COLUMNS)


def issue_to_json_obj(i):
    return {
        "key": i.key,
        "project": i.project,
        "number": i.number,
        "title": i.title,
        "description": i.description,
        "type": i.type,
        "status": i.status,
        "priority": i.priority,
        "assignee": i.assignee,
        "reporter": i.reporter,
        "labels": list(i.labels),
        "watchers": list(i.watchers),
        "due": i.due,
        "estimate": i.estimate,
        "created_at": i.created_at,
        "updated_at": i.updated_at,
        "closed_at": i.closed_at,
    }


def issues_to_json(issues):
    return json.dumps([issue_to_json_obj(i) for i in issues], indent=2, ensure_ascii=False) + "\n"


def issue_table_row(i):
    return [i.key, i.type, i.status, i.priority, i.assignee or "-", i.due or "-",
            truncate(i.title, TITLE_WIDTH)]


def issues_to_table(issues):
    issues = list(issues)
    table = render_table(["Key", "Type", "Status", "Pri", "Assignee", "Due", "Title"],
                         [issue_table_row(i) for i in issues])
    n_open = sum(1 for i in issues if i.is_open)
    return f"{table}\n\n{plural(len(issues), 'issue')} ({n_open} open)\n"


# ---- comments ----------------------------------------------------------------

def comments_to_csv(comments):
    return _csv([[c.id, c.issue, c.author, c.created_at, c.body] for c in comments],
                ("id", "issue", "author", "created", "body"))


def comments_to_json(comments):
    return json.dumps([{"id": c.id, "issue": c.issue, "author": c.author, "created_at": c.created_at,
                        "body": c.body} for c in comments], indent=2, ensure_ascii=False) + "\n"


def comments_to_table(comments):
    rows = [[c.id, c.issue, c.author or "-", c.created_at, truncate(" ".join(c.body.split()), 50)]
            for c in comments]
    return render_table(["Id", "Issue", "Author", "Created", "Body"], rows, align="r") + "\n"


# ---- events ------------------------------------------------------------------

def _details_json(details):
    return json.dumps(details, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def events_to_csv(events):
    return _csv([[e.seq, e.timestamp, e.actor, e.action, e.subject, _details_json(e.details)]
                 for e in events], ("seq", "timestamp", "actor", "action", "subject", "details"))


def events_to_json(events):
    return json.dumps([{"seq": e.seq, "timestamp": e.timestamp, "actor": e.actor,
                        "action": e.action, "subject": e.subject, "details": e.details}
                       for e in events], indent=2, ensure_ascii=False) + "\n"


def events_to_table(events):
    rows = [[e.seq, e.timestamp, e.actor, e.action, e.subject] for e in events]
    return render_table(["Seq", "Timestamp", "Actor", "Action", "Subject"], rows, align="r") + "\n"


# ---- dispatch ----------------------------------------------------------------

FORMATTERS = {
    "issues": {"csv": issues_to_csv, "json": issues_to_json, "table": issues_to_table},
    "comments": {"csv": comments_to_csv, "json": comments_to_json, "table": comments_to_table},
    "events": {"csv": events_to_csv, "json": events_to_json, "table": events_to_table},
}


def render(kind, records, fmt):
    try:
        formatter = FORMATTERS[kind][fmt]
    except KeyError:
        raise ValidationError(f"cannot export {kind} as {fmt}") from None
    return formatter(list(records))
