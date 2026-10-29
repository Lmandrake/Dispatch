"""Handlers: users, projects, members, db."""

from trellis.table import render_table


def user_add(ctx):
    a = ctx.args
    u = ctx.tracker.add_user(a.username, a.display_name, email=a.email)
    ctx.print(f"created user {u.username}")


def user_list(ctx):
    rows = [[u.username, u.display_name, u.email or "-", "yes" if u.active else "no"]
            for u in ctx.tracker.users()]
    ctx.print(render_table(["User", "Name", "Email", "Active"], rows))


def user_deactivate(ctx):
    u = ctx.tracker.deactivate_user(ctx.args.username)
    ctx.print(f"deactivated {u.username}")


def user_reactivate(ctx):
    u = ctx.tracker.reactivate_user(ctx.args.username)
    ctx.print(f"reactivated {u.username}")


def project_create(ctx):
    a = ctx.args
    p = ctx.tracker.create_project(a.key, a.name, description=a.description, lead=a.lead)
    ctx.print(f"created project {p.key}")


def project_list(ctx):
    t = ctx.tracker
    rows = []
    for p in t.visible_projects():
        if p.archived and not ctx.args.all:
            continue
        n_open = sum(1 for i in t.repo.list_issues(p.key) if i.is_open)
        rows.append([p.key, p.name, p.lead or "-", n_open, "archived" if p.archived else ""])
    ctx.print(render_table(["Key", "Name", "Lead", "Open", ""], rows, align="lllr"))


def project_show(ctx):
    t = ctx.tracker
    p = t.project(ctx.args.key)
    ctx.print(f"Key:          {p.key}")
    ctx.print(f"Name:         {p.name}")
    ctx.print(f"Lead:         {p.lead or '-'}")
    ctx.print(f"Archived:     {'yes' if p.archived else 'no'}")
    ctx.print(f"Next number:  {p.next_number}")
    ctx.print(f"Created:      {p.created_at}")
    if p.description:
        ctx.print("")
        ctx.print(p.description)
    ctx.print("")
    rows = [[m.username, m.role] for m in t.members(p.key)]
    ctx.print(render_table(["Member", "Role"], rows))


def project_update(ctx):
    a = ctx.args
    changes = {k: getattr(a, k) for k in ("name", "description", "lead") if getattr(a, k) is not None}
    p = ctx.tracker.update_project(a.key, **changes)
    ctx.print(f"updated project {p.key}")


def project_archive(ctx):
    p = ctx.tracker.archive_project(ctx.args.key)
    ctx.print(f"archived {p.key}")


def project_unarchive(ctx):
    p = ctx.tracker.unarchive_project(ctx.args.key)
    ctx.print(f"unarchived {p.key}")


def member_add(ctx):
    a = ctx.args
    m = ctx.tracker.add_member(a.project, a.username, a.role)
    ctx.print(f"{m.username} is now a {m.role} of {m.project}")


def member_role(ctx):
    a = ctx.args
    m = ctx.tracker.set_role(a.project, a.username, a.role)
    ctx.print(f"{m.username} is now a {m.role} of {m.project}")


def member_remove(ctx):
    a = ctx.args
    ctx.tracker.remove_member(a.project, a.username)
    ctx.print(f"removed {a.username.lower()} from {a.project.upper()}")


def member_list(ctx):
    rows = [[m.username, m.role] for m in ctx.tracker.members(ctx.args.project)]
    ctx.print(render_table(["Member", "Role"], rows))


def db_info(ctx):
    repo = ctx.tracker.repo
    ctx.print(f"Backend:   {repo.backend}")
    ctx.print(f"Version:   {repo.schema_version}")
    if repo.opened_version != repo.schema_version:
        ctx.print(f"On disk:   {repo.opened_version} (upgraded in memory; run 'db upgrade')")
    ctx.print(f"Users:     {len(repo.list_users())}")
    ctx.print(f"Projects:  {len(repo.list_projects())}")
    ctx.print(f"Issues:    {len(repo.list_issues())}")
    ctx.print(f"Comments:  {len(repo.list_comments())}")
    ctx.print(f"Events:    {len(repo.list_events())}")


def db_upgrade(ctx):
    repo = ctx.tracker.repo
    before = repo.opened_version
    if not ctx.tracker.is_system:
        from trellis.errors import PermissionDenied
        raise PermissionDenied("only the system user may upgrade the database")
    repo.commit()
    if repo.backend == "json" and before != repo.schema_version:
        repo._write(repo.to_document())
    if before == repo.schema_version:
        ctx.print(f"already at version {repo.schema_version}")
    else:
        ctx.print(f"upgraded from version {before} to {repo.schema_version}")


def db_copy(ctx):
    from trellis.errors import PermissionDenied
    from trellis.storage import open_repository
    from trellis.transfer import copy_repository, dump

    if not ctx.tracker.is_system:
        raise PermissionDenied("only the system user may copy the database")
    dst = open_repository(ctx.args.dest)
    try:
        copied = copy_repository(ctx.tracker.repo, dst)
    finally:
        dst.close()
    same = copied == dump(ctx.tracker.repo)
    ctx.print(f"copied {len(copied['issues'])} issues and {len(copied['events'])} events "
              f"to {ctx.args.dest} ({dst.backend})" + ("" if same else " -- WARNING: copy differs"))
    return 0 if same else 1


def db_check(ctx):
    from trellis.checks import check_repository

    problems = check_repository(ctx.tracker.repo)
    for problem in problems:
        ctx.print(str(problem))
    if problems:
        ctx.print(f"{len(problems)} problem(s)")
        return 1
    ctx.print("ok")
