"""User management."""

from dataclasses import replace

from trellis.errors import ConflictError, ValidationError
from trellis.models import User
from trellis.services.base import SYSTEM, transactional
from trellis.validation import check_display_name, check_email, normalize_username


class UsersMixin:
    @transactional
    def add_user(self, username, display_name, email=""):
        self.require_site_admin()
        username = normalize_username(username)
        if username == SYSTEM:
            raise ValidationError("'system' is reserved")
        if self.repo.get_user(username) is not None:
            raise ConflictError(f"user {username} already exists")
        user = User(username=username, display_name=check_display_name(display_name),
                    email=check_email(email), created_at=self.clock())
        self.repo.save_user(user)
        self.audit.record(self.actor, "user.created", username,
                          display_name=user.display_name, email=user.email)
        return user

    @transactional
    def deactivate_user(self, username):
        self.require_site_admin()
        user = self._user(username)
        if not user.active:
            raise ConflictError(f"user {user.username} is already deactivated")
        if user.username == self.actor:
            raise ValidationError("you cannot deactivate yourself")
        user = replace(user, active=False)
        self.repo.save_user(user)
        # Deactivated users cannot hold work: unassign their open issues.
        for issue in self.repo.issues_assigned_to(user.username):
            if issue.is_open:
                after = replace(issue, assignee="", updated_at=self.clock())
                self._save_issue(after)
                self._dated_changed(issue, after)
                self.audit.record(self.actor, "issue.assigned", issue.key,
                                  **{"from": user.username, "to": ""})
        self.audit.record(self.actor, "user.deactivated", user.username)
        return user

    @transactional
    def reactivate_user(self, username):
        self.require_site_admin()
        user = self._user(username)
        if user.active:
            raise ConflictError(f"user {user.username} is active")
        user = replace(user, active=True)
        self.repo.save_user(user)
        self.audit.record(self.actor, "user.reactivated", user.username)
        return user
