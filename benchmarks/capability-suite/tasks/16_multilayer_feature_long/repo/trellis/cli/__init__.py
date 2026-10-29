"""Command line interface: ``python3 -m trellis [--db PATH] [--as USER] COMMAND ...``.

The database comes from ``--db``, else ``TRELLIS_DB``, else the ``db``
setting of ``~/.trellisrc`` (see ``trellis.config``), else ``trellis.json``
in the current directory; the backend is chosen from the
path (see ``trellis.storage``).  The acting user comes from ``--as``, else
``TRELLIS_USER``, else the ``user`` setting, else the built-in ``system`` superuser.  ``TRELLIS_NOW``
fixes the clock (``YYYY-MM-DDTHH:MM:SSZ``).

Exit status: 0 on success, 1 for a TrellisError (printed to stderr as
``error: <message>``), 2 for a usage error (argparse's own behaviour).

The full command reference is docs/CLI.md; the parser is built in
``trellis.cli.parser`` and the handlers live in ``trellis.cli.commands_*``.
"""

import os
import sys

from trellis.clock import utc_now
from trellis.config import load_settings
from trellis.errors import TrellisError
from trellis.services import Tracker
from trellis.storage import open_repository

DEFAULT_DB = "trellis.json"


class Context:
    """What every command handler gets: the parsed args, the tracker, the
    database path and the output streams."""

    def __init__(self, args, tracker, db_path, out, err):
        self.args = args
        self.tracker = tracker
        self.db_path = db_path
        self.out = out
        self.err = err

    def print(self, *parts, **kw):
        print(*parts, file=self.out, **kw)

    def write(self, text):
        self.out.write(text)


def main(argv=None, out=None, err=None):
    from trellis.cli.parser import build_parser

    out = out or sys.stdout
    err = err or sys.stderr
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    repo = None
    try:
        settings = load_settings()
        db = args.db or os.environ.get("TRELLIS_DB") or settings.db or DEFAULT_DB
        actor = args.as_user or os.environ.get("TRELLIS_USER") or settings.user or "system"
        repo = open_repository(db)
        tracker = Tracker(repo, actor=actor, clock=utc_now)
        if not tracker.is_system and repo.get_user(tracker.actor) is None:
            raise TrellisError(f"no such user: {tracker.actor}")
        ctx = Context(args, tracker, db, out, err)
        rc = args.handler(ctx)
        return 0 if rc is None else rc
    except TrellisError as exc:
        print(f"error: {exc}", file=err)
        return 1
    finally:
        if repo is not None:
            repo.close()
