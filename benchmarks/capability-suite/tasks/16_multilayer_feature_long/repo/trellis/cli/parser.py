"""The argparse tree.  Each sub-command's ``handler`` is set with
``set_defaults(handler=...)``; ``trellis.cli.main`` calls it with a
``Context``."""

import argparse

from trellis.cli import commands_admin as A
from trellis.cli import commands_issues as I
from trellis.cli import commands_views as V
from trellis.models import PRIORITIES, STATUSES, TYPES

FORMATS = ("table", "csv", "json")


def _int(text):
    try:
        return int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {text!r}") from None


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(self._err_stream())
        self.exit(2, f"{self.prog}: error: {message}\n")

    @staticmethod
    def _err_stream():
        import sys
        return sys.stderr


def build_parser():
    p = _Parser(prog="trellis", description="A small project and issue tracker.")
    p.add_argument("--db", help="database path (.json, .db, :memory:)")
    p.add_argument("--as", dest="as_user", metavar="USER", help="act as this user")
    sub = p.add_subparsers(dest="command", required=True, parser_class=_Parser)

    # ---- users ---------------------------------------------------------------
    user = sub.add_parser("user", help="manage users")
    us = user.add_subparsers(dest="user_command", required=True, parser_class=_Parser)
    x = us.add_parser("add")
    x.add_argument("username")
    x.add_argument("display_name")
    x.add_argument("--email", default="")
    x.set_defaults(handler=A.user_add)
    x = us.add_parser("list")
    x.set_defaults(handler=A.user_list)
    x = us.add_parser("deactivate")
    x.add_argument("username")
    x.set_defaults(handler=A.user_deactivate)
    x = us.add_parser("reactivate")
    x.add_argument("username")
    x.set_defaults(handler=A.user_reactivate)

    # ---- projects ------------------------------------------------------------
    proj = sub.add_parser("project", help="manage projects")
    ps = proj.add_subparsers(dest="project_command", required=True, parser_class=_Parser)
    x = ps.add_parser("create")
    x.add_argument("key")
    x.add_argument("name")
    x.add_argument("--description", default="")
    x.add_argument("--lead", default="")
    x.set_defaults(handler=A.project_create)
    x = ps.add_parser("list")
    x.add_argument("--all", action="store_true", help="include archived projects")
    x.set_defaults(handler=A.project_list)
    x = ps.add_parser("show")
    x.add_argument("key")
    x.set_defaults(handler=A.project_show)
    x = ps.add_parser("update")
    x.add_argument("key")
    x.add_argument("--name")
    x.add_argument("--description")
    x.add_argument("--lead")
    x.set_defaults(handler=A.project_update)
    x = ps.add_parser("archive")
    x.add_argument("key")
    x.set_defaults(handler=A.project_archive)
    x = ps.add_parser("unarchive")
    x.add_argument("key")
    x.set_defaults(handler=A.project_unarchive)

    # ---- members -------------------------------------------------------------
    mem = sub.add_parser("member", help="manage project members")
    ms = mem.add_subparsers(dest="member_command", required=True, parser_class=_Parser)
    x = ms.add_parser("add")
    x.add_argument("project")
    x.add_argument("username")
    x.add_argument("role", choices=("viewer", "member", "admin"))
    x.set_defaults(handler=A.member_add)
    x = ms.add_parser("role")
    x.add_argument("project")
    x.add_argument("username")
    x.add_argument("role", choices=("viewer", "member", "admin"))
    x.set_defaults(handler=A.member_role)
    x = ms.add_parser("remove")
    x.add_argument("project")
    x.add_argument("username")
    x.set_defaults(handler=A.member_remove)
    x = ms.add_parser("list")
    x.add_argument("project")
    x.set_defaults(handler=A.member_list)

    # ---- issues --------------------------------------------------------------
    x = sub.add_parser("create", help="create an issue")
    x.add_argument("project")
    x.add_argument("title")
    x.add_argument("--description", "-d", default="")
    x.add_argument("--type", "-t", default="task", choices=TYPES)
    x.add_argument("--priority", "-p", default="normal", choices=PRIORITIES)
    x.add_argument("--assignee", "-a", default="")
    x.add_argument("--label", "-l", action="append", default=[])
    x.add_argument("--due", default="", help="YYYY-MM-DD or relative (+3d, tomorrow, ...)")
    x.add_argument("--estimate", "-e", type=_int)
    x.set_defaults(handler=I.create)

    x = sub.add_parser("edit", help="change an issue's fields")
    x.add_argument("key")
    x.add_argument("--title")
    x.add_argument("--description", "-d")
    x.add_argument("--type", "-t", choices=TYPES)
    x.add_argument("--priority", "-p", choices=PRIORITIES)
    x.add_argument("--due", help="date, relative date, or 'none' to clear")
    x.add_argument("--estimate", "-e", help="integer, or 'none' to clear")
    x.set_defaults(handler=I.edit)

    x = sub.add_parser("show", help="show one issue")
    x.add_argument("key")
    x.add_argument("--json", action="store_true")
    x.add_argument("--timeline", action="store_true", help="events and comments in time order")
    x.set_defaults(handler=I.show)

    x = sub.add_parser("list", help="list issues")
    x.add_argument("--project", "-P")
    x.add_argument("--where", "-w", default="")
    x.add_argument("--sort", default="key")
    x.add_argument("--reverse", action="store_true")
    x.add_argument("--limit", type=_int)
    x.add_argument("--format", "-f", default="table", choices=FORMATS)
    x.set_defaults(handler=I.list_issues)

    x = sub.add_parser("move", help="change an issue's status")
    x.add_argument("key")
    x.add_argument("status", choices=STATUSES + tuple(s.replace("_", "-") for s in STATUSES if "_" in s))
    x.set_defaults(handler=I.move)

    x = sub.add_parser("close", help="close an issue (done)")
    x.add_argument("key")
    x.add_argument("--wontfix", action="store_true")
    x.set_defaults(handler=I.close)

    x = sub.add_parser("reopen")
    x.add_argument("key")
    x.set_defaults(handler=I.reopen)

    x = sub.add_parser("assign", help="assign an issue ('-' to unassign)")
    x.add_argument("key")
    x.add_argument("username")
    x.set_defaults(handler=I.assign)

    x = sub.add_parser("label")
    x.add_argument("key")
    x.add_argument("labels", nargs="+")
    x.set_defaults(handler=I.label)

    x = sub.add_parser("unlabel")
    x.add_argument("key")
    x.add_argument("labels", nargs="+")
    x.set_defaults(handler=I.unlabel)

    x = sub.add_parser("watch")
    x.add_argument("key")
    x.add_argument("--user")
    x.set_defaults(handler=I.watch)

    x = sub.add_parser("unwatch")
    x.add_argument("key")
    x.add_argument("--user")
    x.set_defaults(handler=I.unwatch)

    x = sub.add_parser("comment", help="add a comment")
    x.add_argument("key")
    x.add_argument("body")
    x.set_defaults(handler=I.comment)

    x = sub.add_parser("comments", help="list an issue's comments")
    x.add_argument("key")
    x.set_defaults(handler=I.comments)

    x = sub.add_parser("delete", help="delete an issue and its comments")
    x.add_argument("key")
    x.set_defaults(handler=I.delete)

    bulk = sub.add_parser("bulk", help="change many issues at once")
    bs = bulk.add_subparsers(dest="bulk_command", required=True, parser_class=_Parser)
    x = bs.add_parser("move")
    x.add_argument("status")
    x.add_argument("keys", nargs="+")
    x.set_defaults(handler=I.bulk_move)
    x = bs.add_parser("assign")
    x.add_argument("username")
    x.add_argument("keys", nargs="+")
    x.set_defaults(handler=I.bulk_assign)
    x = bs.add_parser("label")
    x.add_argument("label")
    x.add_argument("keys", nargs="+")
    x.set_defaults(handler=I.bulk_label)

    # ---- views ---------------------------------------------------------------
    x = sub.add_parser("explain", help="show how a --where query is parsed")
    x.add_argument("query", nargs="?", default="")
    x.add_argument("--fields", action="store_true", help="list every query field")
    x.add_argument("--project", "-P")
    x.set_defaults(handler=V.explain)

    x = sub.add_parser("board", help="open issues of a project by status")
    x.add_argument("project")
    x.set_defaults(handler=V.board)

    x = sub.add_parser("next", help="what to work on next")
    x.add_argument("project")
    x.add_argument("--user")
    x.add_argument("--limit", type=_int, default=5)
    x.set_defaults(handler=V.next_up)

    x = sub.add_parser("agenda", help="open issues due soon")
    x.add_argument("--days", type=_int, default=14)
    x.add_argument("--user")
    x.set_defaults(handler=V.agenda)

    x = sub.add_parser("history", help="the audit trail")
    x.add_argument("--subject")
    x.add_argument("--action")
    x.add_argument("--actor")
    x.add_argument("--since", type=_int, default=0)
    x.add_argument("--project", "-P")
    x.add_argument("--json", action="store_true")
    x.set_defaults(handler=V.history)

    x = sub.add_parser("report", help="text reports")
    x.add_argument("name", nargs="?", default="summary")
    x.add_argument("--project", "-P")
    x.set_defaults(handler=V.report)

    x = sub.add_parser("export", help="export issues, comments or events")
    x.add_argument("kind", choices=("issues", "comments", "events"))
    x.add_argument("--format", "-f", default="csv", choices=FORMATS)
    x.add_argument("--project", "-P")
    x.add_argument("--where", "-w", default="")
    x.add_argument("--output", "-o")
    x.set_defaults(handler=V.export)

    x = sub.add_parser("import", help="import issues from CSV")
    x.add_argument("project")
    x.add_argument("file")
    x.set_defaults(handler=V.import_csv)

    x = sub.add_parser("digest", help="what a user should know about")
    x.add_argument("--user")
    x.add_argument("--mark", action="store_true", help="remember that the user has seen it")
    x.add_argument("--all", action="store_true", help="ignore the saved cursor")
    x.add_argument("--mail", action="store_true", help="print as an e-mail message")
    x.set_defaults(handler=V.digest)

    x = sub.add_parser("stats", help="lead and cycle time of done issues")
    x.add_argument("project")
    x.add_argument("--per-issue", action="store_true")
    x.set_defaults(handler=V.stats)

    db = sub.add_parser("db", help="database maintenance")
    ds = db.add_subparsers(dest="db_command", required=True, parser_class=_Parser)
    x = ds.add_parser("info")
    x.set_defaults(handler=A.db_info)
    x = ds.add_parser("upgrade", help="rewrite the database in the current format")
    x.set_defaults(handler=A.db_upgrade)
    x = ds.add_parser("check", help="look for inconsistencies")
    x.set_defaults(handler=A.db_check)
    x = ds.add_parser("copy", help="copy everything into another (empty) database")
    x.add_argument("dest")
    x.set_defaults(handler=A.db_copy)

    return p
