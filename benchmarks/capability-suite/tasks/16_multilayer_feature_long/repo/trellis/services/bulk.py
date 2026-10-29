"""Operations on many issues at once.  Each is a single transaction: if any
issue fails, nothing changes."""

from trellis import permissions as P
from trellis.errors import ValidationError
from trellis.services.base import transactional
from trellis.services.issues import _created_details
from trellis.validation import check_status

IMPORT_KEYS = ("title", "description", "type", "priority", "assignee", "labels", "due", "estimate")


class BulkMixin:
    @transactional
    def bulk_transition(self, keys, status):
        """Move every issue in ``keys`` to ``status``.  Returns the updated
        issues in the order given."""
        target = check_status(status)
        out = []
        for key in _unique(keys):
            issue = self._writable_issue(key)
            out.append(self._apply_transition(issue, target))
        return out

    @transactional
    def bulk_assign(self, keys, username):
        return [self.assign(key, username) for key in _unique(keys)]

    @transactional
    def bulk_label(self, keys, *labels):
        return [self.label(key, *labels) for key in _unique(keys)]

    @transactional
    def bulk_matching(self, project_key, where, status):
        """Transition every issue of a project that matches a query."""
        project = self._project(project_key)
        self.require(project.key, P.WRITE)
        hits = self.search(where, project=project.key)
        keys = [i.key for i in hits if i.status != status]
        return self.bulk_transition(keys, status)

    @transactional
    def import_issues(self, project_key, rows):
        """Create one issue per row (a dict with ``title`` and any of
        ``IMPORT_KEYS``).  All or nothing: a bad row raises ValidationError
        naming its 1-based row number and nothing is imported."""
        project = self._project(project_key)
        self.require(project.key, P.IMPORT)
        self.require_writable(project)
        created = []
        for n, row in enumerate(rows, start=1):
            unknown = set(row) - set(IMPORT_KEYS)
            if unknown:
                raise ValidationError(f"row {n}: unknown column(s) {', '.join(sorted(unknown))}")
            if not row.get("title"):
                raise ValidationError(f"row {n}: title is required")
            project = self._project(project.key)
            try:
                issue = self._build_issue(
                    project,
                    title=row["title"],
                    description=row.get("description", ""),
                    type=row.get("type") or "task",
                    priority=row.get("priority") or "normal",
                    assignee=row.get("assignee", ""),
                    labels=row.get("labels", ()),
                    due=row.get("due", ""),
                    estimate=row.get("estimate"),
                )
            except ValidationError as exc:
                raise ValidationError(f"row {n}: {exc}") from None
            except Exception as exc:  # NotFoundError for an unknown assignee, ...
                raise ValidationError(f"row {n}: {exc}") from None
            self._insert_issue(project, issue)
            self.audit.record(self.actor, "issue.created", issue.key,
                              **_created_details(issue, imported=True))
            created.append(issue)
        return created


def _unique(keys):
    seen, out = set(), []
    for k in keys:
        k = k.strip().upper()
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out
