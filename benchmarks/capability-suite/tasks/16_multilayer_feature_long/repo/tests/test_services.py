import pytest

from tests.helpers import make_repo, make_tracker
from trellis.errors import ConflictError, NotFoundError, PermissionDenied, ValidationError
from trellis.transfer import dump


@pytest.fixture
def env(backend):
    repo = make_repo(backend)
    return make_tracker(repo)


def test_create_issue_numbers_and_event(env):
    t, _ = env
    ana = t.as_user("ana")
    i1 = ana.create_issue("WEB", "  First   issue ", labels=["UI", "ui"], due="2026-05-10")
    i2 = ana.create_issue("web", "Second")
    assert (i1.key, i2.key) == ("WEB-1", "WEB-2")
    assert i1.title == "First issue" and i1.labels == ("ui",)
    assert i1.reporter == "ana" and i1.watchers == ("ana",)
    ev = t.audit.events(subject="WEB-1")[0]
    assert ev.actor == "ana"
    assert ev.details == {"title": "First issue", "type": "task", "priority": "normal",
                          "due": "2026-05-10", "labels": ["ui"]}
    assert t.audit.events(subject="WEB-2")[0].details == {
        "title": "Second", "type": "task", "priority": "normal"}


def test_permissions(env):
    t, _ = env
    t.create_issue("WEB", "x")
    with pytest.raises(PermissionDenied):
        t.as_user("cyd").create_issue("WEB", "viewer cannot")
    with pytest.raises(PermissionDenied):
        t.as_user("dan").issue("WEB-1")
    with pytest.raises(PermissionDenied):
        t.as_user("bob").delete_issue("WEB-1")
    t.as_user("cyd").watch("WEB-1")
    assert t.issue("WEB-1").watchers == ("cyd",)
    with pytest.raises(PermissionDenied):
        t.as_user("bob").watch("WEB-1", "ana")


def test_workflow(env):
    t, clock = env
    bob = t.as_user("bob")
    bob.create_issue("WEB", "x")
    clock.advance(60)
    done = bob.close("WEB-1")
    assert done.status == "done" and done.closed_at == "2026-05-01T09:01:00Z"
    with pytest.raises(ValidationError):
        bob.transition("WEB-1", "review")
    assert bob.reopen("WEB-1").closed_at == ""


def test_failed_call_leaves_no_trace(env, backend):
    t, _ = env
    t.create_issue("WEB", "a")
    before = dump(t.repo)
    with pytest.raises(NotFoundError):
        t.bulk_transition(["WEB-1", "WEB-7"], "done")
    assert dump(t.repo) == before
    with pytest.raises(ValidationError, match="row 2"):
        t.import_issues("WEB", [{"title": "ok"}, {"title": "bad", "priority": "huge"}])
    assert dump(t.repo) == before


def test_assignee_rules(env):
    t, _ = env
    t.create_issue("WEB", "a", assignee="bob")
    with pytest.raises(ValidationError):
        t.assign("WEB-1", "cyd")
    t.set_role("WEB", "bob", "viewer")
    assert t.issue("WEB-1").assignee == ""
    with pytest.raises(ConflictError):
        t.set_role("WEB", "ana", "member")


def test_board_and_next_use_rank_order(env):
    t, _ = env
    t.create_issue("WEB", "low", priority="low")
    t.create_issue("WEB", "urgent late", priority="urgent", due="2026-06-01")
    t.create_issue("WEB", "urgent soon", priority="urgent", due="2026-05-05")
    t.create_issue("WEB", "blocked", priority="high")
    t.transition("WEB-4", "blocked")
    assert [i.key for i in t.board("WEB")["open"]] == ["WEB-3", "WEB-2", "WEB-1"]
    assert [i.key for i in t.next_up("WEB")] == ["WEB-3", "WEB-2", "WEB-1"]
    t.update_issue("WEB-1", priority="urgent")
    assert [i.key for i in t.board("WEB")["open"]][0] == "WEB-3"
    assert [i.key for i in t.next_up("WEB")] == ["WEB-3", "WEB-2", "WEB-1"]
    t.update_issue("WEB-2", due="2026-05-02")
    assert [i.key for i in t.next_up("WEB")] == ["WEB-2", "WEB-3", "WEB-1"]


def test_agenda_and_cache(env):
    t, clock = env
    t.create_issue("WEB", "a", due="2026-05-03")
    t.create_issue("OPS", "b", due="2026-04-30")
    t.create_issue("WEB", "c")
    assert [(i.key, d) for i, d in t.agenda()] == [("OPS-1", -1), ("WEB-1", 2)]
    t.close("OPS-1")
    assert [i.key for i, _ in t.agenda()] == ["WEB-1"]
    t.update_issue("WEB-2", due="2026-05-02")
    assert [i.key for i, _ in t.agenda()] == ["WEB-2", "WEB-1"]
    assert [i.key for i, _ in t.as_user("bob").agenda()] == ["WEB-2", "WEB-1"]
    assert t.as_user("dan").agenda() == []


def test_comments_and_mentions(env):
    t, _ = env
    t.create_issue("WEB", "a")
    c = t.as_user("bob").add_comment("WEB-1", "ping @ana and @dan and @nobody")
    assert c.id == 1
    assert t.audit.events(action="comment.added")[0].details == {"id": 1, "mentions": ["ana"]}


def test_archived_project_read_only(env):
    t, _ = env
    t.create_issue("WEB", "a")
    t.archive_project("WEB")
    with pytest.raises(ConflictError):
        t.create_issue("WEB", "b")
    with pytest.raises(ConflictError):
        t.as_user("ana").close("WEB-1")
    t.unarchive_project("WEB")
    t.close("WEB-1")


def test_deactivate_unassigns(env):
    t, _ = env
    t.create_issue("WEB", "a", assignee="bob", due="2026-05-04")
    assert [i.assignee for i, _ in t.agenda()] == ["bob"]
    t.deactivate_user("bob")
    assert t.issue("WEB-1").assignee == ""
    assert [i.assignee for i, _ in t.agenda()] == [""]


def test_update_issue_rejects_other_fields(env):
    t, _ = env
    t.create_issue("WEB", "a")
    for field in ("status", "assignee", "labels", "watchers", "reporter"):
        with pytest.raises(ValidationError):
            t.update_issue("WEB-1", **{field: "x"})
