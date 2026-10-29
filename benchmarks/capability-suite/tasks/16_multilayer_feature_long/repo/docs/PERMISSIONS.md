# Permissions

Roles are per project: `viewer` < `member` < `admin`.  The built-in
`system` user (the CLI's default actor) passes every check.  A user who is
not a member of a project cannot see it: reads raise `PermissionDenied`
and searches leave its issues out.

| operation | viewer | member | admin |
|---|---|---|---|
| read issues, comments, history | yes | yes | yes |
| watch / unwatch for yourself | yes | yes | yes |
| watch / unwatch for someone else | - | - | yes |
| create, edit, transition, assign, label, comment | - | yes | yes |
| bulk operations | - | yes | yes |
| delete issues | - | - | yes |
| import issues | - | - | yes |
| add / remove members, change roles | - | - | yes |
| update, archive, unarchive the project | - | - | yes |

* Deactivated users can do nothing; their open issues are unassigned when
  they are deactivated.
* Only active members and admins can be assignees.  Demoting someone to
  viewer, or removing them, unassigns their open issues in that project.
* A project always keeps at least one admin.
* An archived project is read-only for everyone (`ConflictError`); only
  unarchiving is allowed.
* User management (`user add`, `deactivate`, `reactivate`) needs the
  system user or someone who is an admin of at least one project.

The table is implemented by `trellis/permissions.py`; the checks are made
in the service methods (`TrackerBase.require`).
