"""Handlers: boards, agenda, history, reports, export/import, digest."""

import json
import os

from trellis.audit import format_event
from trellis.errors import TrellisError, ValidationError
from trellis.export import render
from trellis.importer import parse_issues_csv
from trellis.notify import build_digest, load_cursor, render_digest, save_cursor
from trellis.report import run_report
from trellis.storage.codec import event_to_dict
from trellis.table import render_table, truncate

STATUS_TITLES = {"open": "Open", "in_progress": "In progress", "review": "Review",
                 "blocked": "Blocked"}


def board(ctx):
    columns = ctx.tracker.board(ctx.args.project)
    blocks = []
    for status, issues in columns.items():
        lines = [f"{STATUS_TITLES[status]} ({len(issues)})"]
        for i in issues:
            who = f" @{i.assignee}" if i.assignee else ""
            due = f" due {i.due}" if i.due else ""
            lines.append(f"  {i.key} [{i.priority}]{who}{due}  {truncate(i.title, 50)}")
        blocks.append("\n".join(lines))
    ctx.print("\n\n".join(blocks))


def next_up(ctx):
    issues = ctx.tracker.next_up(ctx.args.project, username=ctx.args.user, limit=ctx.args.limit)
    if not issues:
        ctx.print("nothing to do")
        return
    for n, i in enumerate(issues, start=1):
        due = f" due {i.due}" if i.due else ""
        ctx.print(f"{n}. {i.key} [{i.priority}]{due}  {i.title}")


def agenda(ctx):
    items = ctx.tracker.agenda(days=ctx.args.days, username=ctx.args.user)
    if not items:
        ctx.print("nothing due")
        return
    rows = [[i.key, i.due, f"{d:+d}d", i.status, i.assignee or "-", truncate(i.title, 40)]
            for i, d in items]
    ctx.print(render_table(["Key", "Due", "In", "Status", "Assignee", "Title"], rows, align="llr"))


def history(ctx):
    a = ctx.args
    events = ctx.tracker.history(
        subject=a.subject.upper() if a.subject else None, action=a.action, actor=a.actor,
        since=a.since, project=a.project.upper() if a.project else None)
    if a.json:
        ctx.write(json.dumps([event_to_dict(e) for e in events], indent=2) + "\n")
        return
    for e in events:
        ctx.print(format_event(e))


def report(ctx):
    project = ctx.args.project.upper() if ctx.args.project else None
    ctx.write(run_report(ctx.args.name, ctx.tracker, project))


def export(ctx):
    a = ctx.args
    t = ctx.tracker
    project = a.project.upper() if a.project else None
    if a.kind == "issues":
        records = t.search(a.where, project=project)
    elif a.kind == "comments":
        if a.where:
            raise ValidationError("--where only applies to issue exports")
        keys = {i.key for i in t.search("", project=project)}
        records = [c for c in t.repo.list_comments() if c.issue in keys]
    else:
        if a.where:
            raise ValidationError("--where only applies to issue exports")
        records = t.history(project=project)
    text = render(a.kind, records, a.format)
    if a.output:
        try:
            with open(a.output, "w", encoding="utf-8", newline="") as fh:
                fh.write(text)
        except OSError as exc:
            raise TrellisError(f"cannot write {a.output}: {exc}") from None
        ctx.print(f"wrote {len(records)} {a.kind} to {a.output}")
    else:
        ctx.write(text)


def import_csv(ctx):
    path = ctx.args.file
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            text = fh.read()
    except OSError as exc:
        raise TrellisError(f"cannot read {path}: {exc}") from None
    rows = parse_issues_csv(text)
    created = ctx.tracker.import_issues(ctx.args.project, rows)
    if created:
        ctx.print(f"imported {len(created)} issue(s): {created[0].key} .. {created[-1].key}")
    else:
        ctx.print("imported 0 issues")


def digest(ctx):
    t = ctx.tracker
    username = (ctx.args.user or ("" if t.is_system else t.actor)).strip().lower()
    if not username:
        raise ValidationError("digest needs --user when acting as system")
    if username != t.actor and not t.is_system:
        raise ValidationError("you can only read your own digest")
    since = 0 if ctx.args.all else load_cursor(ctx.db_path, username)
    d = build_digest(t, username, since_seq=since)
    if ctx.args.mail:
        from trellis.notify.mailer import digest_message
        msg = digest_message(d, t.repo.get_user(username), t.clock())
        ctx.write(msg.as_string())
    else:
        ctx.write(render_digest(d))
    if ctx.args.mark:
        save_cursor(ctx.db_path, username, d.last_seq)


def explain(ctx):
    from trellis.query.explain import explain as explain_query, field_reference

    if ctx.args.fields:
        ctx.print("\n".join(field_reference()))
        return
    for line in explain_query(ctx.args.query):
        ctx.print(line)
    project = ctx.args.project.upper() if ctx.args.project else None
    hits = ctx.tracker.search(ctx.args.query, project=project)
    ctx.print(f"matches: {len(hits)}")


def stats(ctx):
    from trellis.stats import flow_stats, render_stats

    rows = flow_stats(ctx.tracker, ctx.args.project)
    if ctx.args.per_issue:
        table = render_table(["Key", "Lead", "Cycle"],
                             [[r.key, f"{r.lead_hours}h",
                               "-" if r.cycle_hours is None else f"{r.cycle_hours}h"] for r in rows],
                             align="lrr")
        ctx.print(table)
        ctx.print("")
    ctx.write(render_stats(rows))
