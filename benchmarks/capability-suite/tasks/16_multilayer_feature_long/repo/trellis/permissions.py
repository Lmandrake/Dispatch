"""Who may do what.

Roles are per project (a ``Membership``).  A user who is not a member of a
project cannot see it at all.  Deactivated users can do nothing.

==========================  ======  ======  =====
operation                   viewer  member  admin
==========================  ======  ======  =====
read issues, comments       yes     yes     yes
watch / unwatch (self)      yes     yes     yes
create / edit issues        -       yes     yes
assign, label, transition   -       yes     yes
comment                     -       yes     yes
delete issues               -       -       yes
import issues               -       -       yes
manage members              -       -       yes
archive / unarchive         -       -       yes
==========================  ======  ======  =====

Additional rules:

* only active users with role ``member`` or ``admin`` can be *assignees*;
* a project always keeps at least one admin;
* an archived project is read-only for everyone (``ConflictError``), except
  that an admin may unarchive it.
"""

from trellis.errors import PermissionDenied
from trellis.models import role_rank

READ = "read"
WATCH = "watch"
WRITE = "write"
DELETE = "delete"
IMPORT = "import"
MANAGE = "manage"

REQUIRED_ROLE = {
    READ: "viewer",
    WATCH: "viewer",
    WRITE: "member",
    DELETE: "admin",
    IMPORT: "admin",
    MANAGE: "admin",
}

_VERB = {
    READ: "read",
    WATCH: "watch issues in",
    WRITE: "change issues in",
    DELETE: "delete issues in",
    IMPORT: "import into",
    MANAGE: "manage",
}


def can(role, operation):
    return role_rank(role) >= role_rank(REQUIRED_ROLE[operation])


def require(user, membership, project_key, operation):
    """Raise PermissionDenied unless ``user`` (a User or None) holding
    ``membership`` (a Membership or None) may perform ``operation``."""
    if user is None:
        raise PermissionDenied("no such user")
    if not user.active:
        raise PermissionDenied(f"user {user.username} is deactivated")
    if membership is None:
        raise PermissionDenied(f"{user.username} is not a member of {project_key}")
    if not can(membership.role, operation):
        raise PermissionDenied(
            f"{user.username} is a {membership.role} of {project_key} and may not "
            f"{_VERB[operation]} it"
        )


def can_be_assignee(user, membership):
    return (user is not None and user.active and membership is not None
            and role_rank(membership.role) >= role_rank("member"))
