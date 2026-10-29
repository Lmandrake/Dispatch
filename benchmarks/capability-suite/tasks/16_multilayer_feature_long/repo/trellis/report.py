"""Text reports (``trellis report NAME``).

Each report is a function ``(tracker, project_key_or_None) -> str`` and is
registered in ``REPORTS``.  Tables are rendered with ``render_table``;
numbers are right-aligned.  Every report ends with a newline.

summary     per project: open / closed / overdue counts and open estimate
status      per status of one project: count and estimate total
labels      per label of one project: open and total counts
workload    per member of one project: open issues and estimate total
due         open dated issues across readable projects, bucketed into
            Overdue / Today / This week / Later
velocity    issues closed per ISO week in one project (last 8 weeks)
aging       open issues of one project bucketed by age in days
"""

from collections import Counter
from datetime import timedelta

from trellis.dates import iso_week, parse_date, week_start
from trellis.errors import ValidationError
from trellis.models import OPEN_STATUSES, STATUSES
from trellis.table import render_table, truncate


def _need_project(project):
    if not project:
        raise ValidationError("this report needs --project")
    return project


def summary_report(tracker, project=None):
    today = tracker.today()
    rows = []
    projects = [tracker.project(project)] if project else tracker.visible_projects()
    for p in projects:
        issues = tracker.repo.list_issues(p.key)
        open_ = [i for i in issues if i.is_open]
        overdue = [i for i in open_ if i.due and i.due < today]
        est = sum(i.estimate or 0 for i in open_)
        rows.append([p.key, p.name + (" (archived)" if p.archived else ""), len(open_),
                     len(issues) - len(open_), len(overdue), est])
    return render_table(["Project", "Name", "Open", "Closed", "Overdue", "Estimate"], rows,
                        align="llrrrr") + "\n"


def status_report(tracker, project=None):
    p = tracker.project(_need_project(project))
    counts, est = Counter(), Counter()
    for i in tracker.repo.list_issues(p.key):
        counts[i.status] += 1
        est[i.status] += i.estimate or 0
    rows = [[s, counts[s], est[s]] for s in STATUSES if counts[s]]
    rows.append(["total", sum(counts.values()), sum(est.values())])
    return render_table(["Status", "Issues", "Estimate"], rows, align="lrr") + "\n"


def labels_report(tracker, project=None):
    p = tracker.project(_need_project(project))
    total, open_ = Counter(), Counter()
    unlabeled = [0, 0]
    for i in tracker.repo.list_issues(p.key):
        if not i.labels:
            unlabeled[0] += 1
            unlabeled[1] += int(i.is_open)
        for label in i.labels:
            total[label] += 1
            open_[label] += int(i.is_open)
    rows = [[label, open_[label], total[label]] for label in sorted(total)]
    if unlabeled[0]:
        rows.append(["(none)", unlabeled[1], unlabeled[0]])
    return render_table(["Label", "Open", "Total"], rows, align="lrr") + "\n"


def workload_report(tracker, project=None):
    rows = [[u or "(unassigned)", n, est] for u, n, est in tracker.workload(_need_project(project))]
    return render_table(["Assignee", "Open", "Estimate"], rows, align="lrr") + "\n"


DUE_BUCKETS = ("Overdue", "Today", "This week", "Later")


def _due_bucket(days, today_date, due_date):
    if days < 0:
        return "Overdue"
    if days == 0:
        return "Today"
    if week_start(due_date) == week_start(today_date):
        return "This week"
    return "Later"


def due_report(tracker, project=None):
    """Open dated issues (all readable projects, or one), grouped by bucket.
    Within a bucket issues are in (due, key) order.  Empty buckets are
    left out; with nothing due at all the report says so."""
    today = tracker.today()
    today_date = parse_date(today)
    if project:
        tracker.project(project)
    groups = {b: [] for b in DUE_BUCKETS}
    for issue, days in tracker.agenda(days=36500):
        if project and issue.project != project:
            continue
        groups[_due_bucket(days, today_date, parse_date(issue.due))].append((issue, days))
    out = []
    for bucket in DUE_BUCKETS:
        items = groups[bucket]
        if not items:
            continue
        out.append(f"{bucket} ({len(items)})")
        rows = [[i.key, i.due, f"{d:+d}d", i.assignee or "-", truncate(i.title, 40)] for i, d in items]
        out.append(render_table(["Key", "Due", "In", "Assignee", "Title"], rows, align="llr"))
        out.append("")
    if not out:
        return "Nothing due.\n"
    return "\n".join(out)


def velocity_report(tracker, project=None, weeks=8):
    p = tracker.project(_need_project(project))
    today = parse_date(tracker.today())
    first = week_start(today) - timedelta(weeks=weeks - 1)
    counts = Counter()
    for i in tracker.repo.list_issues(p.key):
        if i.status == "done" and i.closed_at:
            d = parse_date(i.closed_at[:10])
            if d >= first:
                counts[iso_week(d)] += 1
    rows = []
    for n in range(weeks):
        wk = iso_week(first + timedelta(weeks=n))
        rows.append([wk, counts[wk], "#" * counts[wk]])
    return render_table(["Week", "Done", ""], rows, align="lr") + "\n"


AGE_BUCKETS = ((0, 7, "0-7d"), (8, 30, "8-30d"), (31, 90, "31-90d"), (91, None, ">90d"))


def aging_report(tracker, project=None):
    p = tracker.project(_need_project(project))
    today = parse_date(tracker.today())
    counts = Counter()
    for i in tracker.repo.list_issues(p.key):
        if i.status not in OPEN_STATUSES:
            continue
        age = (today - parse_date(i.created_at[:10])).days
        for lo, hi, label in AGE_BUCKETS:
            if age >= lo and (hi is None or age <= hi):
                counts[label] += 1
                break
    rows = [[label, counts[label]] for _, _, label in AGE_BUCKETS]
    return render_table(["Age", "Open"], rows, align="lr") + "\n"


REPORTS = {
    "summary": summary_report,
    "status": status_report,
    "labels": labels_report,
    "workload": workload_report,
    "due": due_report,
    "velocity": velocity_report,
    "aging": aging_report,
}


def run_report(name, tracker, project=None):
    try:
        fn = REPORTS[name]
    except KeyError:
        raise ValidationError(f"unknown report {name!r}; use one of {', '.join(REPORTS)}") from None
    return fn(tracker, project)
