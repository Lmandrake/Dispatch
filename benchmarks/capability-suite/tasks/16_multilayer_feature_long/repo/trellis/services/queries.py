"""Read-only views: search, boards, the agenda, next-up and workload."""

from trellis import permissions as P
from trellis.dates import add_days, days_until, parse_date
from trellis.errors import ValidationError
from trellis.models import OPEN_STATUSES, priority_rank
from trellis.query import compile_query

SORT_KEYS = {
    "key": lambda i: (i.project, i.number),
    "priority": lambda i: (-priority_rank(i.priority), i.project, i.number),
    "due": lambda i: (i.due or "9999-99-99", i.project, i.number),
    "updated": lambda i: (i.updated_at, i.project, i.number),
    "created": lambda i: (i.created_at, i.project, i.number),
    "title": lambda i: (i.title.lower(), i.project, i.number),
}


class QueriesMixin:
    def _readable_issues(self, project=None):
        if project is not None:
            p = self.project(project)
            return self.repo.list_issues(p.key)
        keys = {p.key for p in self.visible_projects()}
        return [i for i in self.repo.list_issues() if i.project in keys]

    def search(self, where="", project=None, sort="key", reverse=False, limit=None):
        """Issues the actor can read that match ``where``."""
        if sort not in SORT_KEYS:
            raise ValidationError(f"unknown sort key {sort!r}; use one of {', '.join(SORT_KEYS)}")
        pred = compile_query(where or "", self.today(), "" if self.is_system else self.actor)
        hits = [i for i in self._readable_issues(project) if pred(i)]
        hits.sort(key=SORT_KEYS[sort], reverse=reverse)
        if limit is not None:
            hits = hits[:limit]
        return hits

    def board(self, project_key):
        """``{status: [issues in rank order]}`` for every open status."""
        project = self.project(project_key)
        columns = {s: [] for s in OPEN_STATUSES}
        for issue in self.views.ordered_open(project.key):
            columns[issue.status].append(issue)
        return columns

    def next_up(self, project_key, username=None, limit=5):
        """The top open issues of a project for a user: assigned to them, or
        unassigned, in rank order, skipping blocked ones."""
        project = self.project(project_key)
        who = username or ("" if self.is_system else self.actor)
        out = []
        for issue in self.views.ordered_open(project.key):
            if issue.status == "blocked":
                continue
            if issue.assignee and issue.assignee != who:
                continue
            out.append(issue)
            if len(out) >= limit:
                break
        return out

    def agenda(self, days=14, username=None):
        """Open dated issues the actor can read, due within ``days`` days
        from today (overdue ones included), optionally only those assigned
        to ``username``.  Returns ``[(issue, days_until_due), ...]`` in
        (due, project, number) order."""
        if days < 0:
            raise ValidationError("days must be >= 0")
        today = self.today()
        horizon = add_days(parse_date(today), days).isoformat()
        readable = {p.key for p in self.visible_projects()}
        out = []
        for issue in self.views.dated_open():
            if issue.project not in readable:
                continue
            if issue.due > horizon:
                continue
            if username is not None and issue.assignee != username:
                continue
            out.append((issue, days_until(issue.due, today)))
        return out

    def workload(self, project_key):
        """``[(username, open_count, estimate_total), ...]`` per assignable
        member of a project, by username, plus ``("", n, est)`` for
        unassigned work when there is any."""
        project = self.project(project_key)
        counts = {}
        for issue in self.views.ordered_open(project.key):
            c = counts.setdefault(issue.assignee, [0, 0])
            c[0] += 1
            c[1] += issue.estimate or 0
        rows = []
        for m in self.repo.list_memberships(project=project.key):
            if m.role == "viewer":
                continue
            n, est = counts.pop(m.username, [0, 0])
            rows.append((m.username, n, est))
        unassigned = counts.pop("", None)
        for username in sorted(counts):  # assignees who left the project
            n, est = counts[username]
            rows.append((username, n, est))
        if unassigned:
            rows.append(("", unassigned[0], unassigned[1]))
        return rows

    def history(self, subject=None, action=None, actor=None, since=0, project=None):
        if project is not None:
            self.project(project)
        elif subject is not None and "-" in subject:
            self.issue(subject)
        elif subject is not None:
            proj = self.repo.get_project(subject.upper())
            if proj is not None:
                self.require(proj.key, P.READ)
        events = self.audit.events(subject=subject, action=action, actor=actor, since_seq=since,
                                   project=project)
        if self.is_system:
            return events
        readable = {p.key for p in self.visible_projects()}
        out = []
        for ev in events:
            if ev.action.startswith(("project.", "member.")):
                if ev.subject in readable:
                    out.append(ev)
            elif ev.action.startswith(("issue.", "comment.")):
                if ev.subject.rpartition("-")[0] in readable:
                    out.append(ev)
        return out
