import pytest

from trellis.errors import QueryError
from trellis.models import Issue
from trellis.query import filter_issues, parse
from trellis.query.ast import to_text

TODAY = "2026-05-01"

ISSUES = [
    Issue("WEB", 1, "Login broken", type="bug", priority="urgent", assignee="bob",
          labels=("auth", "ui"), due="2026-04-28", estimate=3, created_at="2026-04-01T10:00:00Z"),
    Issue("WEB", 2, "Write docs", priority="low", labels=("docs",), status="in_progress",
          created_at="2026-04-20T10:00:00Z"),
    Issue("WEB", 10, "Dark mode", type="story", assignee="ana", due="2026-05-20",
          watchers=("bob",), created_at="2026-04-25T10:00:00Z"),
    Issue("OPS", 1, "Rotate keys", priority="high", status="done", due="2026-04-01",
          closed_at="2026-04-02T10:00:00Z", created_at="2026-03-01T10:00:00Z"),
]


def keys(q, me=""):
    return [i.key for i in filter_issues(ISSUES, q, TODAY, me)]


def test_empty_query_matches_all():
    assert keys("") == ["WEB-1", "WEB-2", "WEB-10", "OPS-1"]


def test_precedence():
    assert to_text(parse("title = x or type = bug and not status = done")) == \
        "(title = x or (type = bug and not status = done))"
    assert to_text(parse("title = x type = bug")) == "(title = x and type = bug)"


def test_text_enum_and_ordered_enum():
    assert keys("title ~ MODE") == ["WEB-10"]
    assert keys("type = bug") == ["WEB-1"]
    assert keys("priority >= high") == ["WEB-1", "OPS-1"]
    assert keys("pri < normal") == ["WEB-2"]
    with pytest.raises(QueryError):
        keys("type > bug")
    with pytest.raises(QueryError):
        keys("status = finished")


def test_dates_and_bools():
    assert keys("overdue") == ["WEB-1"]
    assert keys("due < +7d") == ["WEB-1", "OPS-1"]
    assert keys("due = none") == ["WEB-2"]
    assert keys("due != 2026-04-28") == ["WEB-2", "WEB-10", "OPS-1"]
    assert keys("not open") == ["OPS-1"]
    assert keys("unassigned and open") == ["WEB-2"]
    assert keys("created >= 2026-04-20") == ["WEB-2", "WEB-10"]


def test_users_and_lists():
    assert keys("assignee = me", me="ana") == ["WEB-10"]
    assert keys("mine", me="bob") == ["WEB-1"]
    assert keys("label in (docs, ui)") == ["WEB-1", "WEB-2"]
    assert keys("tag ~ ut") == ["WEB-1"]
    assert keys("watcher = bob") == ["WEB-10"]
    assert keys("estimate = none") == ["WEB-2", "WEB-10", "OPS-1"]


def test_errors_have_positions():
    with pytest.raises(QueryError, match="offset 6"):
        keys("title ")
    with pytest.raises(QueryError, match="unknown field"):
        keys("colour = red")
    with pytest.raises(QueryError, match="does not apply"):
        keys("label < x")
