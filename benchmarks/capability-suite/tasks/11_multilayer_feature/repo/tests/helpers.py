import io

from stockroom.cli import main
from stockroom.clock import FixedClock
from stockroom.services import InventoryService
from stockroom.storage import MemoryRepository


def make_service(repo=None):
    clock = FixedClock()
    return InventoryService(repo or MemoryRepository(), clock=clock), clock


def run_cli(*argv, db):
    out, err = io.StringIO(), io.StringIO()
    rc = main(["--db", str(db), *argv], out=out, err=err)
    return rc, out.getvalue(), err.getvalue()
