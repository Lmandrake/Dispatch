"""Integrity checks over a whole repository (``trellis db check``).

``check_repository(repo)`` returns a list of ``Problem``s, empty when the
data is consistent.  It never changes anything.  The checks:

* every project's ``next_number`` is greater than its highest issue number;
* every issue's project exists;
* labels and watchers are sorted, unique and well-formed;
* every assignee is an active user with role member or admin in the
  issue's project, unless the issue is closed;
* every watcher is a member of the issue's project;
* statuses, priorities and types are known; closed issues have
  ``closed_at`` and open ones do not;
* due dates are valid YYYY-MM-DD dates;
* comments refer to existing issues and have ids below the counter;
* every project has at least one admin;
* event seqs run 1, 2, 3, ... without gaps.
"""

from dataclasses import dataclass

from trellis.dates import is_date
from trellis.errors import ValidationError
from trellis.models import PRIORITIES, STATUSES, TYPES, role_rank
from trellis.validation import normalize_label


@dataclass(frozen=True)
class Problem:
    subject: str
    message: str

    def __str__(self):
        return f"{self.subject}: {self.message}"


def _check_issue(issue, repo, projects, members):
    out = []
    key = issue.key
    if issue.project not in projects:
        out.append(Problem(key, f"project {issue.project} does not exist"))
    if issue.status not in STATUSES:
        out.append(Problem(key, f"unknown status {issue.status!r}"))
    if issue.priority not in PRIORITIES:
        out.append(Problem(key, f"unknown priority {issue.priority!r}"))
    if issue.type not in TYPES:
        out.append(Problem(key, f"unknown type {issue.type!r}"))
    if issue.is_closed and not issue.closed_at:
        out.append(Problem(key, "closed but has no closed_at"))
    if issue.is_open and issue.closed_at:
        out.append(Problem(key, "open but has closed_at"))
    if list(issue.labels) != sorted(set(issue.labels)):
        out.append(Problem(key, "labels are not sorted and unique"))
    for label in issue.labels:
        try:
            if normalize_label(label) != label:
                raise ValidationError(label)
        except ValidationError:
            out.append(Problem(key, f"bad label {label!r}"))
    if list(issue.watchers) != sorted(set(issue.watchers)):
        out.append(Problem(key, "watchers are not sorted and unique"))
    for w in issue.watchers:
        if (issue.project, w) not in members:
            out.append(Problem(key, f"watcher {w} is not a member of {issue.project}"))
    if issue.assignee and issue.is_open:
        m = members.get((issue.project, issue.assignee))
        user = repo.get_user(issue.assignee)
        if user is None:
            out.append(Problem(key, f"assignee {issue.assignee} does not exist"))
        elif not user.active:
            out.append(Problem(key, f"assignee {issue.assignee} is deactivated"))
        elif m is None or role_rank(m.role) < role_rank("member"):
            out.append(Problem(key, f"assignee {issue.assignee} cannot be assigned in {issue.project}"))
    if issue.due and not is_date(issue.due):
        out.append(Problem(key, f"bad due date {issue.due!r}"))
    return out


def check_repository(repo):
    problems = []
    projects = {p.key: p for p in repo.list_projects()}
    members = {(m.project, m.username): m for m in repo.list_memberships()}
    issues = repo.list_issues()
    keys = {i.key for i in issues}

    highest = {}
    for issue in issues:
        highest[issue.project] = max(highest.get(issue.project, 0), issue.number)
        problems.extend(_check_issue(issue, repo, projects, members))
    for key, project in projects.items():
        if project.next_number <= highest.get(key, 0):
            problems.append(Problem(key, f"next_number {project.next_number} is not above "
                                         f"the highest issue number {highest[key]}"))
        if not any(m.role == "admin" for (p, _), m in members.items() if p == key):
            problems.append(Problem(key, "project has no admin"))

    next_cid = repo.peek_comment_id()
    for c in repo.list_comments():
        if c.issue not in keys:
            problems.append(Problem(f"comment {c.id}", f"issue {c.issue} does not exist"))
        if c.id >= next_cid:
            problems.append(Problem(f"comment {c.id}", f"id is not below the counter {next_cid}"))

    for n, ev in enumerate(repo.list_events(), start=1):
        if ev.seq != n:
            problems.append(Problem(f"event {ev.seq}", f"expected seq {n}"))
            break
    return problems
