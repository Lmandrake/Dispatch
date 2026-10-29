import io
import os

from trellis.cli import main
from trellis.clock import FixedClock
from trellis.services import Tracker
from trellis.storage import JsonFileRepository, SqliteRepository

DATA = os.path.join(os.path.dirname(__file__), "data")

BACKENDS = ["json", "sqlite"]


def make_repo(kind, tmp_path=None):
    if kind == "json":
        return JsonFileRepository(None if tmp_path is None else tmp_path / "t.json")
    return SqliteRepository(":memory:" if tmp_path is None else str(tmp_path / "t.db"))


def make_tracker(repo, start="2026-05-01T09:00:00Z"):
    """A system tracker over ``repo`` with users ana (admin), bob (member),
    cyd (viewer) in project WEB, and dan (admin) of project OPS."""
    clock = FixedClock(start)
    t = Tracker(repo, clock=clock)
    t.add_user("ana", "Ana Lima", "ana@example.com")
    t.add_user("bob", "Bob Stone")
    t.add_user("cyd", "Cyd Park")
    t.add_user("dan", "Dan Wu")
    t.create_project("WEB", "Website", lead="ana")
    t.add_member("WEB", "bob", "member")
    t.add_member("WEB", "cyd", "viewer")
    t.create_project("OPS", "Operations", lead="dan")
    return t, clock


def run_cli(db, *argv, user=None):
    out, err = io.StringIO(), io.StringIO()
    args = ["--db", str(db)]
    if user:
        args += ["--as", user]
    rc = main([*args, *argv], out=out, err=err)
    return rc, out.getvalue(), err.getvalue()
