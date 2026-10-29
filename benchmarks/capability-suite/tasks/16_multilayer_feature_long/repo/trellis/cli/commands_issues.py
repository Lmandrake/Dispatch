"""Handlers: creating and changing issues."""

import json

from trellis.clock import today_of
from trellis.dates import resolve_date
from trellis.errors import ValidationError
from trellis.export import issue_to_json_obj, render
from trellis.textutil import join_or_dash, wrap

NONE_WORDS = ("none", "-", "")


def _due(ctx, text):
    if text is None:
        return None
    if text.strip().lower() in NONE_WORDS:
        return ""
    return resolve_date(text, today_of(ctx.tracker.clock))


def create(ctx):
    a = ctx.args
    issue = ctx.tracker.create_issue(
        a.project, a.title, description=a.description, type=a.type, priority=a.priority,
        assignee=a.assignee, labels=a.label, due=_due(ctx, a.due) if a.due else "",
        estimate=a.estimate,
    )
    ctx.print(f"created {issue.key}")


def edit(ctx):
    a = ctx.args
    changes = {}
    for name in ("title", "description", "type", "priority"):
        value = getattr(a, name)
        if value is not None:
            changes[name] = value
    if a.due is not None:
        changes["due"] = _due(ctx, a.due)
    if a.estimate is not None:
        changes["estimate"] = None if a.estimate.strip().lower() in NONE_WORDS else a.estimate
    if not changes:
        raise ValidationError("nothing to change")
    before = ctx.tracker.issue(a.key)
    after = ctx.tracker.update_issue(a.key, **changes)
    if after == before:
        ctx.print(f"{after.key}: no change")
    else:
        ctx.print(f"updated {after.key}")


def show_lines(tracker, issue):
    lines = [
        f"{issue.key}  {issue.title}",
        f"Project:    {issue.project}",
        f"Type:       {issue.type}",
        f"Status:     {issue.status}",
        f"Priority:   {issue.priority}",
        f"Reporter:   {issue.reporter or '-'}",
        f"Assignee:   {issue.assignee or '-'}",
        f"Labels:     {join_or_dash(issue.labels)}",
        f"Watchers:   {join_or_dash(issue.watchers)}",
        f"Due:        {issue.due or '-'}",
        f"Estimate:   {'-' if issue.estimate is None else issue.estimate}",
        f"Created:    {issue.created_at}",
        f"Updated:    {issue.updated_at}",
        f"Closed:     {issue.closed_at or '-'}",
    ]
    if issue.description:
        lines += ["", wrap(issue.description, width=72)]
    comments = tracker.comments(issue.key)
    if comments:
        lines += ["", f"Comments ({len(comments)})"]
        for c in comments:
            lines.append(f"  [{c.id}] {c.author or 'system'} {c.created_at}")
            lines.append(wrap(c.body, width=68, indent="    "))
    return lines


def show(ctx):
    t = ctx.tracker
    issue = t.issue(ctx.args.key)
    if ctx.args.timeline:
        from trellis.timeline import render_timeline, timeline
        ctx.write(render_timeline(timeline(t, issue.key)))
        return
    if ctx.args.json:
        obj = issue_to_json_obj(issue)
        obj["comments"] = [{"id": c.id, "author": c.author, "body": c.body, "created_at": c.created_at}
                           for c in t.comments(issue.key)]
        ctx.write(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")
        return
    ctx.print("\n".join(show_lines(t, issue)))


def list_issues(ctx):
    a = ctx.args
    issues = ctx.tracker.search(a.where, project=a.project.upper() if a.project else None,
                                sort=a.sort, reverse=a.reverse, limit=a.limit)
    ctx.write(render("issues", issues, a.format))


def move(ctx):
    issue = ctx.tracker.transition(ctx.args.key, ctx.args.status.replace("-", "_"))
    ctx.print(f"{issue.key}: {issue.status}")


def close(ctx):
    issue = ctx.tracker.close(ctx.args.key, "wontfix" if ctx.args.wontfix else "done")
    ctx.print(f"{issue.key}: {issue.status}")


def reopen(ctx):
    issue = ctx.tracker.reopen(ctx.args.key)
    ctx.print(f"{issue.key}: {issue.status}")


def assign(ctx):
    who = "" if ctx.args.username in ("-", "none") else ctx.args.username
    issue = ctx.tracker.assign(ctx.args.key, who)
    ctx.print(f"{issue.key}: assigned to {issue.assignee or 'nobody'}")


def _labels_line(issue):
    return f"{issue.key}: labels {', '.join(issue.labels)}" if issue.labels else f"{issue.key}: no labels"


def label(ctx):
    ctx.print(_labels_line(ctx.tracker.label(ctx.args.key, *ctx.args.labels)))


def unlabel(ctx):
    ctx.print(_labels_line(ctx.tracker.unlabel(ctx.args.key, *ctx.args.labels)))


def watch(ctx):
    issue = ctx.tracker.watch(ctx.args.key, ctx.args.user)
    ctx.print(f"{issue.key}: watchers {join_or_dash(issue.watchers)}")


def unwatch(ctx):
    issue = ctx.tracker.unwatch(ctx.args.key, ctx.args.user)
    ctx.print(f"{issue.key}: watchers {join_or_dash(issue.watchers)}")


def comment(ctx):
    c = ctx.tracker.add_comment(ctx.args.key, ctx.args.body)
    ctx.print(f"comment {c.id} added to {c.issue}")


def comments(ctx):
    for c in ctx.tracker.comments(ctx.args.key):
        ctx.print(f"[{c.id}] {c.author or 'system'} {c.created_at}")
        ctx.print(wrap(c.body, width=72, indent="  "))


def delete(ctx):
    issue = ctx.tracker.issue(ctx.args.key)
    ctx.tracker.delete_issue(issue.key)
    ctx.print(f"deleted {issue.key}")


def bulk_move(ctx):
    issues = ctx.tracker.bulk_transition(ctx.args.keys, ctx.args.status.replace("-", "_"))
    ctx.print(f"moved {len(issues)} issue(s) to {ctx.args.status.replace('-', '_')}")


def bulk_assign(ctx):
    who = "" if ctx.args.username in ("-", "none") else ctx.args.username
    issues = ctx.tracker.bulk_assign(ctx.args.keys, who)
    ctx.print(f"assigned {len(issues)} issue(s) to {who or 'nobody'}")


def bulk_label(ctx):
    issues = ctx.tracker.bulk_label(ctx.args.keys, ctx.args.label)
    ctx.print(f"labelled {len(issues)} issue(s) {ctx.args.label.strip().lower()}")
