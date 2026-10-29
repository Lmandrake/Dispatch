"""Projects and memberships."""

from dataclasses import replace

from trellis import permissions as P
from trellis.errors import ConflictError, NotFoundError, PermissionDenied, ValidationError
from trellis.models import Membership, Project
from trellis.services.base import transactional
from trellis.validation import (
    check_description,
    check_project_name,
    check_role,
    normalize_project_key,
    normalize_username,
)

PROJECT_FIELDS = ("name", "description", "lead")


class ProjectsMixin:
    @transactional
    def create_project(self, key, name, description="", lead=""):
        key = normalize_project_key(key)
        if not self.is_system:
            user = self.repo.get_user(self.actor)
            if user is None or not user.active:
                raise PermissionDenied(f"{self.actor} may not create projects")
        if self.repo.get_project(key) is not None:
            raise ConflictError(f"project {key} already exists")
        lead = normalize_username(lead) if lead else ("" if self.is_system else self.actor)
        if lead and self.repo.get_user(lead) is None:
            raise NotFoundError(f"no such user: {lead}")
        project = Project(key=key, name=check_project_name(name),
                          description=check_description(description), lead=lead,
                          created_at=self.clock())
        self.repo.save_project(project)
        self.audit.record(self.actor, "project.created", key, name=project.name)
        if not self.is_system:
            self.repo.save_membership(Membership(key, self.actor, "admin"))
            self.audit.record(self.actor, "member.added", key, username=self.actor, role="admin")
        if lead and lead != self.actor:
            self.repo.save_membership(Membership(key, lead, "admin"))
            self.audit.record(self.actor, "member.added", key, username=lead, role="admin")
        return project

    @transactional
    def update_project(self, key, **changes):
        project = self._project(key)
        self.require(project.key, P.MANAGE)
        self.require_writable(project)
        unknown = set(changes) - set(PROJECT_FIELDS)
        if unknown:
            raise ValidationError(f"cannot update {', '.join(sorted(unknown))}")
        clean = {}
        if "name" in changes:
            clean["name"] = check_project_name(changes["name"])
        if "description" in changes:
            clean["description"] = check_description(changes["description"])
        if "lead" in changes:
            lead = normalize_username(changes["lead"]) if changes["lead"] else ""
            if lead and self.repo.get_membership(project.key, lead) is None:
                raise ValidationError(f"{lead} is not a member of {project.key}")
            clean["lead"] = lead
        diff = {f: [getattr(project, f), v] for f, v in clean.items() if getattr(project, f) != v}
        if not diff:
            return project
        project = replace(project, **clean)
        self.repo.save_project(project)
        self.audit.record(self.actor, "project.updated", project.key, changes=diff)
        return project

    @transactional
    def archive_project(self, key):
        project = self._project(key)
        self.require(project.key, P.MANAGE)
        if project.archived:
            raise ConflictError(f"project {project.key} is already archived")
        project = replace(project, archived=True)
        self.repo.save_project(project)
        self.audit.record(self.actor, "project.archived", project.key)
        return project

    @transactional
    def unarchive_project(self, key):
        project = self._project(key)
        self.require(project.key, P.MANAGE)
        if not project.archived:
            raise ConflictError(f"project {project.key} is not archived")
        project = replace(project, archived=False)
        self.repo.save_project(project)
        self.audit.record(self.actor, "project.unarchived", project.key)
        return project

    # ---- members ---------------------------------------------------------
    def members(self, key):
        project = self.project(key)
        return self.repo.list_memberships(project=project.key)

    @transactional
    def add_member(self, key, username, role):
        project = self._project(key)
        self.require(project.key, P.MANAGE)
        self.require_writable(project)
        user = self._user(username)
        role = check_role(role)
        if self.repo.get_membership(project.key, user.username) is not None:
            raise ConflictError(f"{user.username} is already a member of {project.key}")
        self.repo.save_membership(Membership(project.key, user.username, role))
        self.audit.record(self.actor, "member.added", project.key, username=user.username, role=role)
        return self.repo.get_membership(project.key, user.username)

    @transactional
    def set_role(self, key, username, role):
        project = self._project(key)
        self.require(project.key, P.MANAGE)
        self.require_writable(project)
        username = normalize_username(username)
        m = self.repo.get_membership(project.key, username)
        if m is None:
            raise NotFoundError(f"{username} is not a member of {project.key}")
        role = check_role(role)
        if role == m.role:
            return m
        if m.role == "admin" and self._admin_count(project.key) == 1:
            raise ConflictError(f"{project.key} must keep at least one admin")
        self.repo.save_membership(replace(m, role=role))
        self.audit.record(self.actor, "member.role_changed", project.key,
                          username=username, old=m.role, new=role)
        if role == "viewer":
            self._unassign_open(project.key, username)
        return self.repo.get_membership(project.key, username)

    @transactional
    def remove_member(self, key, username):
        project = self._project(key)
        self.require(project.key, P.MANAGE)
        self.require_writable(project)
        username = normalize_username(username)
        m = self.repo.get_membership(project.key, username)
        if m is None:
            raise NotFoundError(f"{username} is not a member of {project.key}")
        if m.role == "admin" and self._admin_count(project.key) == 1:
            raise ConflictError(f"{project.key} must keep at least one admin")
        self.repo.delete_membership(project.key, username)
        self.audit.record(self.actor, "member.removed", project.key, username=username)
        self._unassign_open(project.key, username)
        if project.lead == username:
            self.repo.save_project(replace(project, lead=""))

    def _admin_count(self, project_key):
        return sum(1 for m in self.repo.list_memberships(project=project_key) if m.role == "admin")

    def _unassign_open(self, project_key, username):
        for issue in self.repo.issues_assigned_to(username):
            if issue.project == project_key and issue.is_open:
                after = replace(issue, assignee="", updated_at=self.clock())
                self._save_issue(after)
                self._dated_changed(issue, after)
                self.audit.record(self.actor, "issue.assigned", issue.key,
                                  **{"from": username, "to": ""})
