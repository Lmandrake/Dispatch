"""Copying a whole database, e.g. from a JSON file into SQLite.

``copy_repository(src, dst)`` copies every user, project, membership,
issue, comment and audit event, plus the comment-id counter, and commits
``dst``.  ``dst`` must be empty.  Nothing is re-validated or re-numbered:
the copy is exact, so ``dump(src) == dump(dst)`` afterwards.

``dump(repo)`` is a backend-neutral snapshot (plain dicts in canonical
order) used by ``db copy --check`` and by the tests that hold the two
backends to identical behaviour.
"""

from trellis.errors import ConflictError
from trellis.storage import codec


def dump(repo):
    return {
        "next_comment_id": repo.peek_comment_id(),
        "users": [codec.user_to_dict(u) for u in repo.list_users()],
        "projects": [codec.project_to_dict(p) for p in repo.list_projects()],
        "memberships": [codec.membership_to_dict(m) for m in repo.list_memberships()],
        "issues": [codec.issue_to_dict(i) for i in repo.list_issues()],
        "comments": [codec.comment_to_dict(c) for c in repo.list_comments()],
        "events": [codec.event_to_dict(e) for e in repo.list_events()],
    }


def is_empty(repo):
    return not (repo.list_users() or repo.list_projects() or repo.list_issues()
                or repo.list_events())


def copy_repository(src, dst):
    if not is_empty(dst):
        raise ConflictError("destination database is not empty")
    try:
        for u in src.list_users():
            dst.save_user(u)
        for p in src.list_projects():
            dst.save_project(p)
        for m in src.list_memberships():
            dst.save_membership(m)
        for i in src.list_issues():
            dst.save_issue(i)
        for c in src.list_comments():
            dst.add_comment(c)
        for e in src.list_events():
            dst.append_event(e)
        dst.set_comment_id(src.peek_comment_id())
    except BaseException:
        dst.rollback()
        raise
    dst.commit()
    return dump(dst)
