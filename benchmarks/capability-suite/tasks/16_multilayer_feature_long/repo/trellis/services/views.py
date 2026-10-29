"""Ordered views of open issues, cached.

Boards, ``next``, the workload report, the agenda and the digest all want
open issues in some fixed order, and computing that means loading and
sorting many issues.  ``IssueViews`` keeps two kinds of cached list:

``ordered_open(project)``
    the open issues of one project in *rank order*: priority (urgent
    first), then due date (earliest first, no due date last), then number.
    Dropped by ``invalidate(project)``.

``dated_open()``
    the open issues of *every* project that have a due date, ordered by
    (due, project, number).  Used by the agenda, the ``due`` report and
    the digest.  Dropped by ``invalidate_dated()``.

The caches hold Issue objects, not keys, so they go stale as soon as an
issue they contain changes in a way their consumers can see.  The two are
invalidated separately because rebuilding the cross-project list is the
expensive one and most edits cannot affect what it is used for.

What the consumers of each view display (and filter or sort on):

* ``ordered_open``: board, next, workload -- key, status, priority, due,
  assignee, estimate, title.
* ``dated_open``: agenda, the ``due`` report, the digest's Overdue / Due
  soon sections -- key, project, due, status, assignee, title.

The rules for service code:

* after any change to an issue, call ``invalidate(issue.project)``
  (``TrackerBase._save_issue`` does this for you);
* additionally call ``invalidate_dated()`` when the change could alter
  what a ``dated_open`` consumer shows, i.e. it touches one of the fields
  listed above on an issue that has a due date before *or* after the
  change, or creates or deletes a dated issue.  ``TrackerBase.
  _dated_changed(before, after)`` drops the view when either version has a
  due date (pass ``None`` for "did not exist"); call it from every such
  path.  Label and watcher changes skip it on purpose: no dated consumer
  shows labels or watchers.  If a consumer starts showing a new field,
  every path that changes that field must call ``_dated_changed``;
* ``clear()`` both whenever the repository is rolled back
  (``services.base.transactional`` does this).

``hits`` / ``misses`` count cache use (the tests look at them).
"""

from trellis.models import priority_rank


def rank_key(issue):
    return (-priority_rank(issue.priority), issue.due or "9999-99-99", issue.number)


def dated_key(issue):
    return (issue.due, issue.project, issue.number)


class IssueViews:
    def __init__(self, repo):
        self.repo = repo
        self._open = {}
        self._dated = None
        self.hits = 0
        self.misses = 0

    def ordered_open(self, project):
        cached = self._open.get(project)
        if cached is not None:
            self.hits += 1
            return list(cached)
        self.misses += 1
        issues = [i for i in self.repo.list_issues(project) if i.is_open]
        issues.sort(key=rank_key)
        self._open[project] = tuple(issues)
        return list(issues)

    def dated_open(self):
        if self._dated is not None:
            self.hits += 1
            return list(self._dated)
        self.misses += 1
        issues = [i for i in self.repo.list_issues() if i.is_open and i.due]
        issues.sort(key=dated_key)
        self._dated = tuple(issues)
        return list(issues)

    def invalidate(self, project):
        self._open.pop(project, None)

    def invalidate_dated(self):
        self._dated = None

    def clear(self):
        self._open.clear()
        self._dated = None
