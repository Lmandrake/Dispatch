"""Issues: create, edit, move through the workflow, assign, label, watch,
delete."""

from dataclasses import replace

from trellis import permissions as P
from trellis import workflow
from trellis.errors import ValidationError
from trellis.models import Issue
from trellis.services.base import transactional
from trellis.validation import (
    check_description,
    check_due,
    check_estimate,
    check_priority,
    check_status,
    check_title,
    check_type,
    normalize_label,
    normalize_labels,
    normalize_username,
)

#: Fields ``update_issue`` accepts.  Status, assignee, labels and watchers
#: have their own methods (and audit events).
EDITABLE_FIELDS = ("title", "description", "type", "priority", "due", "estimate")

_CHECKS = {
    "title": check_title,
    "description": check_description,
    "type": check_type,
    "priority": check_priority,
    "due": check_due,
    "estimate": check_estimate,
}


class IssuesMixin:
    # ---- create ------------------------------------------------------------
    @transactional
    def create_issue(self, project_key, title, description="", type="task", priority="normal",
                     assignee="", labels=(), due="", estimate=None):
        project = self._project(project_key)
        self.require(project.key, P.WRITE)
        self.require_writable(project)
        issue = self._build_issue(project, title=title, description=description, type=type,
                                  priority=priority, assignee=assignee, labels=labels, due=due,
                                  estimate=estimate)
        self._insert_issue(project, issue)
        self.audit.record(self.actor, "issue.created", issue.key, **_created_details(issue))
        return issue

    def _build_issue(self, project, title, description="", type="task", priority="normal",
                     assignee="", labels=(), due="", estimate=None):
        """Validate everything and return an unsaved Issue numbered with the
        project's next number.  Does not change the repository."""
        now = self.clock()
        reporter = "" if self.is_system else self.actor
        return Issue(
            project=project.key,
            number=project.next_number,
            title=check_title(title),
            description=check_description(description),
            type=check_type(type),
            priority=check_priority(priority),
            reporter=reporter,
            assignee=self._check_assignee(project.key, assignee),
            labels=normalize_labels(labels),
            watchers=(reporter,) if reporter else (),
            due=check_due(due),
            estimate=check_estimate(estimate),
            created_at=now,
            updated_at=now,
        )

    def _insert_issue(self, project, issue):
        """Store a new issue built by ``_build_issue`` and advance the
        project's counter."""
        self.repo.save_project(replace(project, next_number=issue.number + 1))
        self._save_issue(issue)
        self._dated_changed(None, issue)

    # ---- edit --------------------------------------------------------------
    @transactional
    def update_issue(self, key, **changes):
        issue = self._writable_issue(key)
        unknown = set(changes) - set(EDITABLE_FIELDS)
        if unknown:
            raise ValidationError(f"cannot update {', '.join(sorted(unknown))} with update_issue")
        clean = {f: _CHECKS[f](v) for f, v in changes.items()}
        diff = {f: [getattr(issue, f), v] for f, v in clean.items() if getattr(issue, f) != v}
        if not diff:
            return issue
        after = replace(issue, updated_at=self.clock(), **{f: clean[f] for f in diff})
        self._save_issue(after)
        self._dated_changed(issue, after)
        self.audit.record(self.actor, "issue.updated", issue.key, changes=diff)
        return after

    @transactional
    def transition(self, key, status):
        issue = self._writable_issue(key)
        return self._apply_transition(issue, check_status(status))

    def _apply_transition(self, issue, target):
        """Move ``issue`` (already permission-checked) to ``target``, save it
        and record the event.  Shared by ``transition`` and
        ``bulk_transition``."""
        workflow.check_transition(issue.status, target)
        now = self.clock()
        closed_at = now if workflow.closes(target) else ""
        after = replace(issue, status=target, updated_at=now, closed_at=closed_at)
        self._save_issue(after)
        self._dated_changed(issue, after)
        self.audit.record(self.actor, "issue.transitioned", issue.key,
                          **{"from": issue.status, "to": target})
        return after

    def close(self, key, resolution="done"):
        if resolution not in ("done", "wontfix"):
            raise ValidationError("resolution must be done or wontfix")
        return self.transition(key, resolution)

    def reopen(self, key):
        return self.transition(key, "open")

    @transactional
    def assign(self, key, username):
        issue = self._writable_issue(key)
        target = self._check_assignee(issue.project, username) if username else ""
        if target == issue.assignee:
            return issue
        after = replace(issue, assignee=target, updated_at=self.clock())
        self._save_issue(after)
        self._dated_changed(issue, after)
        self.audit.record(self.actor, "issue.assigned", issue.key,
                          **{"from": issue.assignee, "to": target})
        return after

    @transactional
    def label(self, key, *labels):
        issue = self._writable_issue(key)
        new = normalize_labels(labels)
        added = sorted(set(new) - set(issue.labels))
        if not added:
            return issue
        after = replace(issue, labels=normalize_labels(issue.labels + tuple(added)),
                        updated_at=self.clock())
        self._save_issue(after)
        self.audit.record(self.actor, "issue.labeled", issue.key, added=added)
        return after

    @transactional
    def unlabel(self, key, *labels):
        issue = self._writable_issue(key)
        drop = {normalize_label(t) for t in labels}
        removed = sorted(drop & set(issue.labels))
        if not removed:
            return issue
        after = replace(issue, labels=tuple(t for t in issue.labels if t not in drop),
                        updated_at=self.clock())
        self._save_issue(after)
        self.audit.record(self.actor, "issue.unlabeled", issue.key, removed=removed)
        return after

    # ---- watching ----------------------------------------------------------
    @transactional
    def watch(self, key, username=None):
        issue = self._issue(key)
        project = self._project(issue.project)
        self.require(issue.project, P.WATCH)
        self.require_writable(project)
        username = self._watch_target(issue.project, username)
        if username in issue.watchers:
            return issue
        after = replace(issue, watchers=tuple(sorted(issue.watchers + (username,))))
        self._save_issue(after)
        self.audit.record(self.actor, "issue.watched", issue.key, username=username)
        return after

    @transactional
    def unwatch(self, key, username=None):
        issue = self._issue(key)
        project = self._project(issue.project)
        self.require(issue.project, P.WATCH)
        self.require_writable(project)
        username = self._watch_target(issue.project, username)
        if username not in issue.watchers:
            return issue
        after = replace(issue, watchers=tuple(w for w in issue.watchers if w != username))
        self._save_issue(after)
        self.audit.record(self.actor, "issue.unwatched", issue.key, username=username)
        return after

    def _watch_target(self, project_key, username):
        """Members may only (un)watch for themselves; admins (and the
        system actor) may do it for any member."""
        if username is None:
            if self.is_system:
                raise ValidationError("the system user cannot watch issues; name a user")
            return self.actor
        username = normalize_username(username)
        if username != self.actor:
            self.require(project_key, P.MANAGE)
        if self.repo.get_membership(project_key, username) is None:
            raise ValidationError(f"{username} is not a member of {project_key}")
        return username

    # ---- delete ------------------------------------------------------------
    @transactional
    def delete_issue(self, key):
        issue = self._issue(key)
        project = self._project(issue.project)
        self.require(issue.project, P.DELETE)
        self.require_writable(project)
        self.repo.delete_comments(issue.key)
        self.repo.delete_issue(issue.project, issue.number)
        self.views.invalidate(issue.project)
        self._dated_changed(issue, None)
        self.audit.record(self.actor, "issue.deleted", issue.key, title=issue.title)

    # ---- helpers -----------------------------------------------------------
    def _writable_issue(self, key):
        issue = self._issue(key)
        project = self._project(issue.project)
        self.require(issue.project, P.WRITE)
        self.require_writable(project)
        return issue


def _created_details(issue, imported=False):
    details = {"title": issue.title, "type": issue.type, "priority": issue.priority}
    if issue.assignee:
        details["assignee"] = issue.assignee
    if issue.due:
        details["due"] = issue.due
    if issue.labels:
        details["labels"] = list(issue.labels)
    if issue.estimate is not None:
        details["estimate"] = issue.estimate
    if imported:
        details["imported"] = True
    return details
