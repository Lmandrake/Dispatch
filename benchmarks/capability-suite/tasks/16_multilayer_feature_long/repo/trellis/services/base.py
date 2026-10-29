"""Shared plumbing for the Tracker mixins: transactions, the acting user,
permission checks and lookups."""

import functools

from trellis import permissions as P
from trellis.audit import AuditLog
from trellis.clock import today_of, utc_now
from trellis.errors import ConflictError, NotFoundError, PermissionDenied, ValidationError
from trellis.models import User
from trellis.services.views import IssueViews
from trellis.validation import normalize_issue_key, normalize_project_key, normalize_username

#: The built-in superuser.  It exists implicitly (it is never stored), passes
#: every permission check and is the default actor of the CLI.
SYSTEM = "system"


def transactional(method):
    """Run ``method`` as one transaction: commit on success; on any
    exception roll the repository back, drop cached views, and re-raise."""

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        if self._depth:
            return method(self, *args, **kwargs)
        self._depth += 1
        try:
            result = method(self, *args, **kwargs)
        except BaseException:
            self.repo.rollback()
            self.views.clear()
            raise
        finally:
            self._depth -= 1
        self.repo.commit()
        return result

    return wrapper


class TrackerBase:
    def __init__(self, repo, actor=SYSTEM, clock=utc_now):
        self.repo = repo
        self.clock = clock
        self.audit = AuditLog(repo, clock)
        self.views = IssueViews(repo)
        self._depth = 0
        self.actor = SYSTEM if actor in (None, "", SYSTEM) else normalize_username(actor)

    # ---- the acting user ---------------------------------------------------
    @property
    def is_system(self):
        return self.actor == SYSTEM

    def acting_user(self):
        if self.is_system:
            return User(SYSTEM, "System")
        return self.repo.get_user(self.actor)

    def today(self):
        return today_of(self.clock)

    def as_user(self, username):
        """A Tracker on the same repository and clock acting as ``username``."""
        return type(self)(self.repo, actor=username, clock=self.clock)

    # ---- permission checks -------------------------------------------------
    def role_in(self, project_key):
        if self.is_system:
            return "admin"
        m = self.repo.get_membership(project_key, self.actor)
        return m.role if m else None

    def require(self, project_key, operation):
        if self.is_system:
            return
        user = self.repo.get_user(self.actor)
        membership = self.repo.get_membership(project_key, self.actor)
        P.require(user, membership, project_key, operation)

    def require_writable(self, project):
        if project.archived:
            raise ConflictError(f"project {project.key} is archived")

    def require_site_admin(self):
        """User management needs the system actor or an admin of any project."""
        if self.is_system:
            return
        user = self.repo.get_user(self.actor)
        if user is None or not user.active:
            raise PermissionDenied(f"{self.actor} may not manage users")
        if not any(m.role == "admin" for m in self.repo.list_memberships(username=self.actor)):
            raise PermissionDenied(f"{self.actor} may not manage users")

    # ---- lookups -------------------------------------------------------------
    def _user(self, username):
        username = normalize_username(username)
        user = self.repo.get_user(username)
        if user is None:
            raise NotFoundError(f"no such user: {username}")
        return user

    def _project(self, key):
        key = normalize_project_key(key)
        project = self.repo.get_project(key)
        if project is None:
            raise NotFoundError(f"no such project: {key}")
        return project

    def _issue(self, key):
        key = normalize_issue_key(key)
        issue = self.repo.get_issue_by_key(key)
        if issue is None:
            raise NotFoundError(f"no such issue: {key}")
        return issue

    def project(self, key):
        project = self._project(key)
        self.require(project.key, P.READ)
        return project

    def issue(self, key):
        issue = self._issue(key)
        self.require(issue.project, P.READ)
        return issue

    def user(self, username):
        return self._user(username)

    def users(self):
        return self.repo.list_users()

    def visible_projects(self):
        """Projects the actor can read, by key."""
        if self.is_system:
            return self.repo.list_projects()
        keys = {m.project for m in self.repo.list_memberships(username=self.actor)}
        return [p for p in self.repo.list_projects() if p.key in keys]

    # ---- saving --------------------------------------------------------------
    def _save_issue(self, issue):
        """Save ``issue`` and drop the cached rank-ordered view of its
        project.  This does *not* touch the cross-project dated view; see
        ``_dated_changed`` and ``trellis.services.views``."""
        self.repo.save_issue(issue)
        self.views.invalidate(issue.project)

    def _dated_changed(self, before, after):
        """Drop the dated view if either version of the issue has a due
        date.  ``before`` / ``after`` may be None (created / deleted)."""
        if (before is not None and before.due) or (after is not None and after.due):
            self.views.invalidate_dated()

    def _check_assignee(self, project_key, username):
        if not username:
            return ""
        username = normalize_username(username)
        user = self.repo.get_user(username)
        if user is None:
            raise NotFoundError(f"no such user: {username}")
        membership = self.repo.get_membership(project_key, username)
        if not P.can_be_assignee(user, membership):
            raise ValidationError(f"{username} cannot be assigned issues in {project_key}")
        return username
