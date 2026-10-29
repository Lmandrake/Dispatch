"""Hidden tests for task 16: recurring issues (docs/RECURRENCE.md)."""

import csv
import io
import json
import os
import shutil
import sqlite3

import pytest

from trellis.cli import main
from trellis.clock import FixedClock
from trellis.errors import ConflictError, NotFoundError, PermissionDenied, QueryError, StorageError, ValidationError
from trellis.models import Issue
from trellis.query import filter_issues
from trellis.report import run_report
from trellis.services import Tracker
from trellis.storage import JsonFileRepository, SqliteRepository, open_repository
from trellis.transfer import dump

HERE = os.path.dirname(os.path.abspath(__file__))
BACKENDS = ["json", "sqlite"]
START = "2026-05-04T09:00:00Z"  # a Monday


# ---- helpers -----------------------------------------------------------------

def recurrence_mod():
    import trellis.recurrence as R
    return R


def make_repo(kind, tmp_path=None):
    if kind == "json":
        return JsonFileRepository(None if tmp_path is None else tmp_path / "h.json")
    return SqliteRepository(":memory:" if tmp_path is None else str(tmp_path / "h.db"))


def world(repo, start=START):
    """ana admin, bob member, cyd viewer, eve member of WEB; dan admin of OPS."""
    clock = FixedClock(start)
    t = Tracker(repo, clock=clock)
    for u, n in (("ana", "Ana Lima"), ("bob", "Bob Stone"), ("cyd", "Cyd Park"), ("dan", "Dan Wu"),
                 ("eve", "Eve Adams")):
        t.add_user(u, n, f"{u}@example.com")
    t.create_project("WEB", "Website", lead="ana")
    t.add_member("WEB", "bob", "member")
    t.add_member("WEB", "cyd", "viewer")
    t.add_member("WEB", "eve", "member")
    t.create_project("OPS", "Operations", lead="dan")
    return t, clock


@pytest.fixture(params=BACKENDS)
def env(request):
    return world(make_repo(request.param))


def run(db, *argv, user=None):
    out, err = io.StringIO(), io.StringIO()
    args = ["--db", str(db)] + (["--as", user] if user else [])
    rc = main([*args, *argv], out=out, err=err)
    return rc, out.getvalue(), err.getvalue()


def ok(db, *argv, user=None):
    rc, out, err = run(db, *argv, user=user)
    assert rc == 0, (argv, out, err)
    return out


@pytest.fixture(params=["json", "db"])
def db(request, tmp_path):
    path = tmp_path / f"cli.{request.param}"
    ok(path, "user", "add", "ana", "Ana Lima", "--email", "ana@example.com")
    ok(path, "user", "add", "bob", "Bob Stone", "--email", "bob@example.com")
    ok(path, "user", "add", "cyd", "Cyd Park")
    ok(path, "project", "create", "WEB", "Website", "--lead", "ana")
    ok(path, "member", "add", "WEB", "bob", "member")
    ok(path, "member", "add", "WEB", "cyd", "viewer")
    return path


def copy_fixture(tmp_path, version, ext):
    dst = tmp_path / f"fx_v{version}.{ext}"
    shutil.copy(os.path.join(HERE, f"hidden_fixture_v{version}.{ext}"), dst)
    return dst


# ---- 1. canonical form ---------------------------------------------------------

CANON = [
    ("every day", "2026-05-04", "every day"),
    ("every 1 days", "2026-05-04", "every day"),
    ("every 3 day", "2026-05-04", "every 3 days"),
    ("EVERY  3   DAYS", "2026-05-04", "every 3 days"),
    ("every week", "2026-05-07", "every week on thu"),
    ("every 2 weeks", "2026-05-07", "every 2 weeks on thu"),
    ("every weeks", "2026-05-09", "every week on sat"),
    ("every 2 weeks on thu,mon", "2026-05-04", "every 2 weeks on mon,thu"),
    ("every 2 weeks on Monday , THURSDAY", "2026-05-04", "every 2 weeks on mon,thu"),
    ("every week on sun,mon,mon", "2026-05-04", "every week on mon,sun"),
    ("every weekday", "2026-05-04", "every week on mon,tue,wed,thu,fri"),
    ("every weekday until 2026-12-31", "2026-05-04", "every week on mon,tue,wed,thu,fri until 2026-12-31"),
    ("every month", "2026-01-31", "every month on 31"),
    ("every month", "2026-02-28", "every month on 28"),
    ("every 1 month on last", "2026-02-10", "every month on last"),
    ("every 6 months on LAST", "2026-02-10", "every 6 months on last"),
    ("every 3 months on 15", "2026-05-04", "every 3 months on 15"),
    ("every month on 1", "2026-05-04", "every month on 1"),
    ("every 2 weeks on mon,thu until 2027-01-01", "2026-05-04", "every 2 weeks on mon,thu until 2027-01-01"),
    ("every day until 2026-05-04", "2026-05-04", "every day until 2026-05-04"),
    ("every 99 days", "2026-05-04", "every 99 days"),
    ("  every   week   on   fri  ", "2026-05-04", "every week on fri"),
]


@pytest.mark.parametrize("text,due,expected", CANON)
def test_canonicalize(text, due, expected):
    R = recurrence_mod()
    assert R.canonicalize(text, due) == expected
    assert R.canonicalize(expected, due) == expected


BAD_RULES = [
    "", "weekly", "every", "every 0 days", "every 100 days", "every -1 days", "every two weeks",
    "every 2", "every fortnight", "every day on mon", "every week on 15", "every month on mon",
    "every month on 1,15", "every month on 0", "every month on 32", "every week on", "every week on mon,",
    "every week on ,mon", "every week on funday", "every week until", "every week until 2027-02-30",
    "every week until 27-01-01", "every week on mon extra", "every weekday on mon", "every 2 weekday",
    "every day until 2026-05-03",
]


@pytest.mark.parametrize("text", BAD_RULES)
def test_canonicalize_rejects(text):
    R = recurrence_mod()
    with pytest.raises(ValidationError):
        R.canonicalize(text, "2026-05-04")


# ---- 2. next due date ------------------------------------------------------------

NEXT = [
    ("every 2 weeks on mon,thu", "2026-05-04", None, "2026-05-07"),
    ("every 2 weeks on mon,thu", "2026-05-07", None, "2026-05-18"),
    ("every week on mon", "2026-05-04", None, "2026-05-11"),
    ("every week on mon,sun", "2026-05-04", None, "2026-05-10"),
    ("every 3 weeks on wed", "2026-05-06", None, "2026-05-27"),
    ("every 2 weeks on mon", "2026-05-07", None, "2026-05-18"),   # due Thu, list says Mon
    ("every weekday", "2026-05-08", None, "2026-05-11"),          # Fri -> Mon
    ("every day", "2026-03-08", None, "2026-03-09"),              # DST day: no effect
    ("every day", "2026-11-01", None, "2026-11-02"),
    ("every 10 days", "2026-12-25", None, "2027-01-04"),
    ("every month on 15", "2026-01-10", None, "2026-01-15"),
    ("every month on 31", "2026-01-31", None, "2026-02-28"),
    ("every month on 31", "2026-02-28", None, "2026-03-31"),
    ("every month on 31", "2026-03-31", None, "2026-04-30"),
    ("every month on last", "2024-01-31", None, "2024-02-29"),
    ("every 12 months on 29", "2024-02-29", None, "2025-02-28"),
    ("every 12 months on 29", "2025-02-28", None, "2026-02-28"),
    ("every 2 months on 30", "2026-12-30", None, "2027-02-28"),
    ("every month", "2026-01-31", None, "2026-02-28"),
    # catch-up: missed occurrences are skipped, a date equal to today is fine
    ("every week on mon", "2026-04-06", "2026-05-04", "2026-05-04"),
    ("every week on mon", "2026-04-06", "2026-05-05", "2026-05-11"),
    ("every 2 weeks on mon,thu", "2026-04-06", "2026-05-01", "2026-05-04"),
    ("every 3 days", "2026-04-01", "2026-04-10", "2026-04-10"),
    ("every month on 31", "2026-01-31", "2026-04-15", "2026-04-30"),
    ("every day", "2026-05-04", "2026-05-01", "2026-05-05"),       # today before due: no effect
    # until is inclusive
    ("every week on mon until 2026-05-11", "2026-05-04", None, "2026-05-11"),
    ("every week on mon until 2026-05-10", "2026-05-04", None, None),
    ("every day until 2026-05-06", "2026-05-01", "2026-05-06", "2026-05-06"),
    ("every day until 2026-05-06", "2026-05-01", "2026-05-07", None),
    ("every day until 2026-04-01", "2026-05-04", None, None),      # until before due: ended, no error
]


@pytest.mark.parametrize("rule,due,today,expected", NEXT)
def test_next_due(rule, due, today, expected):
    assert recurrence_mod().next_due(rule, due, today) == expected


def test_next_due_default_no_catch_up():
    assert recurrence_mod().next_due("every week", "2020-01-06") == "2020-01-13"


# ---- 3. model / service --------------------------------------------------------------

def test_issue_defaults():
    i = Issue("WEB", 1, "x")
    assert i.recurrence == "" and i.spawned_from == ""


def test_create_issue_with_rule_canonical_and_event(env):
    t, _ = env
    issue = t.as_user("bob").create_issue("WEB", "Standup notes", due="2026-05-07",
                                          recurrence="Every 2 Weeks")
    assert issue.recurrence == "every 2 weeks on thu"
    assert t.issue("WEB-1").recurrence == "every 2 weeks on thu"
    ev = t.audit.events(subject="WEB-1")[-1]
    assert ev.action == "issue.created"
    assert ev.details == {"title": "Standup notes", "type": "task", "priority": "normal",
                          "due": "2026-05-07", "recurrence": "every 2 weeks on thu"}


def test_create_issue_without_rule_event_unchanged(env):
    t, _ = env
    t.create_issue("WEB", "Plain", due="2026-05-07")
    assert t.audit.events(subject="WEB-1")[-1].details == {
        "title": "Plain", "type": "task", "priority": "normal", "due": "2026-05-07"}


@pytest.mark.parametrize("kwargs", [dict(recurrence="every week"),
                                    dict(recurrence="every week until 2026-05-01", due="2026-05-04"),
                                    dict(recurrence="every sometimes", due="2026-05-04")])
def test_create_issue_bad_rule_changes_nothing(env, kwargs):
    t, _ = env
    before = dump(t.repo)
    with pytest.raises(ValidationError):
        t.create_issue("WEB", "x", **kwargs)
    assert dump(t.repo) == before


def test_set_recurrence_event_and_noop(env):
    t, clock = env
    t.create_issue("WEB", "x", due="2026-05-04")
    clock.advance(60)
    issue = t.set_recurrence("WEB-1", "every week")
    assert issue.recurrence == "every week on mon"
    assert issue.updated_at == "2026-05-04T09:01:00Z"
    ev = t.audit.events()[-1]
    assert (ev.action, ev.subject, ev.details) == (
        "issue.recurrence_changed", "WEB-1", {"from": "", "to": "every week on mon"})
    n = len(t.audit.events())
    clock.advance(60)
    assert t.set_recurrence("WEB-1", "EVERY WEEK ON MONDAY").updated_at == "2026-05-04T09:01:00Z"
    assert len(t.audit.events()) == n
    t.set_recurrence("WEB-1", "every 2 weeks on mon,fri")
    assert t.audit.events()[-1].details == {"from": "every week on mon", "to": "every 2 weeks on mon,fri"}
    t.set_recurrence("WEB-1", "")
    assert t.issue("WEB-1").recurrence == ""
    assert t.audit.events()[-1].details == {"from": "every 2 weeks on mon,fri", "to": ""}
    n = len(t.audit.events())
    t.set_recurrence("WEB-1", None)
    assert len(t.audit.events()) == n


def test_set_recurrence_needs_due_and_open(env):
    t, _ = env
    t.create_issue("WEB", "no due")
    with pytest.raises(ValidationError):
        t.set_recurrence("WEB-1", "every day")
    t.create_issue("WEB", "closed", due="2026-05-04")
    t.close("WEB-2")
    with pytest.raises(ValidationError):
        t.set_recurrence("WEB-2", "every day")
    assert t.issue("WEB-2").recurrence == ""


def test_clear_recurrence_on_closed_issue(env):
    t, _ = env
    t.create_issue("WEB", "x", due="2026-05-04", recurrence="every day until 2026-05-04")
    t.close("WEB-1")  # series ended: nothing spawned
    assert len(t.repo.list_issues("WEB")) == 1
    assert t.set_recurrence("WEB-1", "").recurrence == ""


@pytest.mark.parametrize("actor,role_setup,expect", [
    ("ana", None, "ok"),                 # admin
    ("bob", "reporter", "ok"),           # member, reporter
    ("bob", "assignee", "ok"),           # member, assignee
    ("bob", None, PermissionDenied),     # member, neither
    ("cyd", None, PermissionDenied),     # viewer
    ("dan", None, PermissionDenied),     # not a member
])
def test_set_recurrence_permissions(env, actor, role_setup, expect):
    t, _ = env
    if role_setup == "reporter":
        t.as_user("bob").create_issue("WEB", "x", due="2026-05-04")
    elif role_setup == "assignee":
        t.as_user("eve").create_issue("WEB", "x", due="2026-05-04", assignee="bob")
    else:
        t.as_user("eve").create_issue("WEB", "x", due="2026-05-04")
    if expect == "ok":
        assert t.as_user(actor).set_recurrence("WEB-1", "every day").recurrence == "every day"
    else:
        with pytest.raises(expect):
            t.as_user(actor).set_recurrence("WEB-1", "every day")
        assert t.issue("WEB-1").recurrence == ""


def test_member_reporter_may_create_with_rule_and_clear(env):
    t, _ = env
    bob = t.as_user("bob")
    bob.create_issue("WEB", "mine", due="2026-05-04", recurrence="every day")
    assert bob.set_recurrence("WEB-1", "").recurrence == ""
    t.as_user("eve").create_issue("WEB", "eve's", due="2026-05-04", recurrence="every day")
    with pytest.raises(PermissionDenied):
        bob.set_recurrence("WEB-2", "")


def test_set_recurrence_archived(env):
    t, _ = env
    t.create_issue("WEB", "x", due="2026-05-04")
    t.archive_project("WEB")
    with pytest.raises(ConflictError):
        t.set_recurrence("WEB-1", "every day")


def test_update_issue_due_rules(env):
    t, _ = env
    t.create_issue("WEB", "x", due="2026-05-04", recurrence="every week until 2026-06-30")
    with pytest.raises(ValidationError):
        t.update_issue("WEB-1", due="")
    with pytest.raises(ValidationError):
        t.update_issue("WEB-1", due="2026-07-01")
    moved = t.update_issue("WEB-1", due="2026-05-06")
    assert (moved.due, moved.recurrence) == ("2026-05-06", "every week on mon until 2026-06-30")
    for field in ("recurrence", "spawned_from"):
        with pytest.raises(ValidationError):
            t.update_issue("WEB-1", **{field: "every day"})


# ---- 4. spawning ------------------------------------------------------------------------

def _recurring(t, **kw):
    args = dict(description="Write it up", type="chore", priority="high", assignee="bob",
                labels=["ops", "weekly"], due="2026-05-04", estimate=2,
                recurrence="every 2 weeks on mon,thu")
    args.update(kw)
    return t.as_user("ana").create_issue("WEB", "Status report", **args)


def test_close_spawns_next_occurrence(env):
    t, clock = env
    _recurring(t)
    t.as_user("eve").watch("WEB-1")
    t.as_user("bob").add_comment("WEB-1", "done for this week")
    clock.advance(3600)
    closed = t.as_user("bob").close("WEB-1")
    assert closed.status == "done"
    new = t.issue("WEB-2")
    assert new.title == "Status report" and new.description == "Write it up"
    assert (new.type, new.priority, new.assignee, new.reporter) == ("chore", "high", "bob", "ana")
    assert new.labels == ("ops", "weekly") and new.estimate == 2
    assert new.watchers == ("ana", "eve")
    assert new.due == "2026-05-07"
    assert new.status == "open" and new.closed_at == ""
    assert new.recurrence == "every 2 weeks on mon,thu"
    assert new.spawned_from == "WEB-1"
    assert new.created_at == new.updated_at == "2026-05-04T10:00:00Z"
    assert t.comments("WEB-2") == []
    assert t.project("WEB").next_number == 3
    assert t.successor("WEB-1").key == "WEB-2"
    assert t.successor("WEB-2") is None


def test_spawn_events(env):
    t, _ = env
    _recurring(t)
    n = len(t.audit.events())
    t.as_user("bob").close("WEB-1")
    evs = t.audit.events()[n:]
    assert [(e.action, e.subject, e.actor) for e in evs] == [
        ("issue.transitioned", "WEB-1", "bob"), ("issue.created", "WEB-2", "bob")]
    assert evs[0].details == {"from": "open", "to": "done"}
    assert evs[1].details == {"title": "Status report", "type": "chore", "priority": "high",
                              "assignee": "bob", "due": "2026-05-07", "labels": ["ops", "weekly"],
                              "estimate": 2, "recurrence": "every 2 weeks on mon,thu",
                              "spawned_from": "WEB-1"}


def test_wontfix_also_spawns_and_chain_continues(env):
    t, _ = env
    _recurring(t)
    t.close("WEB-1", "wontfix")
    assert t.issue("WEB-2").due == "2026-05-07"
    t.transition("WEB-2", "in_progress")
    t.transition("WEB-2", "review")
    t.transition("WEB-2", "done")
    assert (t.issue("WEB-3").due, t.issue("WEB-3").spawned_from) == ("2026-05-18", "WEB-2")


def test_reclose_does_not_spawn_twice(env):
    t, _ = env
    _recurring(t)
    t.close("WEB-1")
    t.reopen("WEB-1")
    n = len(t.audit.events())
    t.close("WEB-1")
    assert [i.key for i in t.repo.list_issues("WEB")] == ["WEB-1", "WEB-2"]
    assert [e.action for e in t.audit.events()[n:]] == ["issue.transitioned"]


def test_reclose_after_successor_deleted_spawns_again(env):
    t, _ = env
    _recurring(t)
    t.close("WEB-1")
    t.delete_issue("WEB-2")
    t.reopen("WEB-1")
    t.close("WEB-1")
    assert t.issue("WEB-3").spawned_from == "WEB-1"


def test_non_closing_transitions_and_plain_issues_do_not_spawn(env):
    t, _ = env
    _recurring(t)
    t.transition("WEB-1", "in_progress")
    t.transition("WEB-1", "blocked")
    t.create_issue("WEB", "plain", due="2026-05-04")
    t.close("WEB-2")
    assert [i.key for i in t.repo.list_issues("WEB")] == ["WEB-1", "WEB-2"]


def test_delete_spawns_nothing(env):
    t, _ = env
    _recurring(t)
    t.delete_issue("WEB-1")
    assert t.repo.list_issues("WEB") == []


def test_catch_up_skips_missed(env):
    t, clock = env
    _recurring(t, due="2026-04-06", recurrence="every week on mon")
    clock.set("2026-05-06T12:00:00Z")
    t.close("WEB-1")
    assert t.issue("WEB-2").due == "2026-05-11"
    assert len(t.repo.list_issues("WEB")) == 2


def test_catch_up_today_is_allowed(env):
    t, clock = env
    _recurring(t, due="2026-04-06", recurrence="every week on mon")
    t.close("WEB-1")  # today is Monday 2026-05-04
    assert t.issue("WEB-2").due == "2026-05-04"


def test_series_end(env):
    t, _ = env
    _recurring(t, recurrence="every 2 weeks on mon,thu until 2026-05-07")
    t.close("WEB-1")
    assert t.issue("WEB-2").due == "2026-05-07"
    n = len(t.audit.events())
    t.close("WEB-2")
    assert [i.key for i in t.repo.list_issues("WEB")] == ["WEB-1", "WEB-2"]
    assert [e.action for e in t.audit.events()[n:]] == ["issue.transitioned"]
    assert t.project("WEB").next_number == 3


def test_assignee_dropped_when_no_longer_assignable(env):
    t, _ = env
    _recurring(t)
    t.add_member("WEB", "dan", "member")
    t.assign("WEB-1", "dan")
    t.set_role("WEB", "dan", "viewer")   # unassigns open issues
    t.assign("WEB-1", "bob")
    t.close("WEB-1")
    assert t.issue("WEB-2").assignee == "bob"
    t.transition("WEB-2", "in_progress")
    t.transition("WEB-2", "done")
    assert t.issue("WEB-3").assignee == "bob"


@pytest.mark.parametrize("who", ["cyd", "dan", "ghost"])
def test_unassignable_assignee_is_dropped(env, who):
    """Old or hand-edited data can hold an assignee who may no longer be
    assigned (a viewer, a non-member, an unknown user): the spawn drops it."""
    from dataclasses import replace
    t, _ = env
    _recurring(t)
    t.repo.save_issue(replace(t.repo.get_issue("WEB", 1), assignee=who))
    t.repo.commit()
    t.close("WEB-1")
    assert t.issue("WEB-2").assignee == ""
    assert "assignee" not in t.audit.events(subject="WEB-2")[0].details


def test_deactivated_assignee_is_dropped(env):
    from dataclasses import replace
    t, _ = env
    _recurring(t)
    t.deactivate_user("eve")
    t.repo.save_issue(replace(t.repo.get_issue("WEB", 1), assignee="eve"))
    t.repo.commit()
    t.close("WEB-1")
    assert t.issue("WEB-2").assignee == ""


def test_watchers_filtered(env):
    t, _ = env
    _recurring(t)
    for u in ("bob", "cyd", "eve"):
        t.watch("WEB-1", u)
    t.remove_member("WEB", "eve")
    t.deactivate_user("bob")
    t.close("WEB-1")
    new = t.issue("WEB-2")
    assert new.watchers == ("ana", "cyd")
    assert new.assignee == ""


def test_bulk_transition_spawns(env):
    t, _ = env
    _recurring(t)
    t.create_issue("WEB", "plain")
    _recurring(t, due="2026-05-05", recurrence="every month on 5", assignee="")
    t.bulk_transition(["WEB-3", "WEB-2", "WEB-1"], "done")
    issues = {i.key: i for i in t.repo.list_issues("WEB")}
    assert sorted(issues) == ["WEB-1", "WEB-2", "WEB-3", "WEB-4", "WEB-5"]
    assert (issues["WEB-4"].spawned_from, issues["WEB-4"].due) == ("WEB-3", "2026-06-05")
    assert (issues["WEB-5"].spawned_from, issues["WEB-5"].due) == ("WEB-1", "2026-05-07")


def test_failed_bulk_rolls_back_spawn(env):
    t, _ = env
    _recurring(t)
    t.create_issue("WEB", "already done")
    t.close("WEB-2")
    before = dump(t.repo)
    with pytest.raises(ValidationError):
        t.bulk_transition(["WEB-1", "WEB-2"], "done")   # WEB-2 is already done
    assert dump(t.repo) == before
    assert t.successor("WEB-1") is None
    assert [i.key for i, _ in t.agenda()] == ["WEB-1"]
    assert [i.key for i in t.board("WEB")["open"]] == ["WEB-1"]
    assert t.create_issue("WEB", "next").key == "WEB-3"


def test_failed_bulk_rolls_back_spawn_unknown_key(env):
    t, _ = env
    _recurring(t)
    before = dump(t.repo)
    with pytest.raises(NotFoundError):
        t.bulk_transition(["WEB-1", "WEB-42"], "done")
    assert dump(t.repo) == before


def test_successor_permission(env):
    t, _ = env
    _recurring(t)
    t.close("WEB-1")
    assert t.as_user("cyd").successor("WEB-1").key == "WEB-2"
    with pytest.raises(PermissionDenied):
        t.as_user("dan").successor("WEB-1")


def test_viewer_cannot_close(env):
    t, _ = env
    _recurring(t)
    with pytest.raises(PermissionDenied):
        t.as_user("cyd").close("WEB-1")
    assert len(t.repo.list_issues("WEB")) == 1


def test_import_with_recurrence(env):
    t, _ = env
    created = t.import_issues("WEB", [
        {"title": "Rotate keys", "due": "2026-05-31", "recurrence": "every month"},
        {"title": "Plain"},
    ])
    assert [i.recurrence for i in created] == ["every month on 31", ""]
    evs = t.audit.events(action="issue.created")
    assert evs[0].details == {"title": "Rotate keys", "type": "task", "priority": "normal",
                              "due": "2026-05-31", "recurrence": "every month on 31", "imported": True}
    assert evs[1].details == {"title": "Plain", "type": "task", "priority": "normal", "imported": True}
    before = dump(t.repo)
    with pytest.raises(ValidationError, match="row 2"):
        t.import_issues("WEB", [{"title": "a"}, {"title": "b", "recurrence": "every day"}])
    assert dump(t.repo) == before


# ---- 5. caches ------------------------------------------------------------------------

def test_agenda_sees_new_rule(env):
    t, _ = env
    t.create_issue("WEB", "x", due="2026-05-06")
    assert [i.recurrence for i, _ in t.agenda()] == [""]
    t.set_recurrence("WEB-1", "every week")
    assert [i.recurrence for i, _ in t.agenda()] == ["every week on wed"]
    t.set_recurrence("WEB-1", "")
    assert [i.recurrence for i, _ in t.agenda()] == [""]


def test_reports_see_new_rule(env):
    t, _ = env
    t.create_issue("WEB", "x", due="2026-05-06")
    assert run_report("recurring", t) == "No recurring issues.\n"
    assert "every" not in run_report("due", t)
    t.set_recurrence("WEB-1", "every week")
    assert "every week on wed" in run_report("due", t)
    assert "WEB-1" in run_report("recurring", t)


def test_views_see_spawned_issue(env):
    t, _ = env
    _recurring(t)
    assert [i.key for i, _ in t.agenda()] == ["WEB-1"]
    assert [i.key for i in t.next_up("WEB", username="bob")] == ["WEB-1"]
    t.close("WEB-1")
    assert [i.key for i, _ in t.agenda()] == ["WEB-2"]
    assert [i.key for i in t.next_up("WEB", username="bob")] == ["WEB-2"]
    assert [i.key for i in t.board("WEB")["open"]] == ["WEB-2"]


def test_sqlite_file_persists_new_columns(tmp_path):
    repo = make_repo("sqlite", tmp_path)
    t, _ = world(repo)
    _recurring(t)
    t.close("WEB-1")
    t.create_issue("WEB", "later", due="2026-06-01")
    t.set_recurrence("WEB-3", "every 3 days")
    expected = dump(repo)
    repo.close()
    again = SqliteRepository(str(tmp_path / "h.db"))
    assert dump(again) == expected
    assert again.get_issue("WEB", 2).spawned_from == "WEB-1"
    assert again.get_issue("WEB", 3).recurrence == "every 3 days"


def test_json_file_persists_new_keys(tmp_path):
    repo = make_repo("json", tmp_path)
    t, _ = world(repo)
    _recurring(t)
    t.close("WEB-1")
    doc = json.loads((tmp_path / "h.json").read_text())
    assert doc["version"] == 5
    rec = doc["issues"][1]
    assert list(rec)[-3:] == ["closed_at", "recurrence", "spawned_from"]
    assert (rec["recurrence"], rec["spawned_from"]) == ("every 2 weeks on mon,thu", "WEB-1")
    assert dump(JsonFileRepository(tmp_path / "h.json")) == dump(repo)


# ---- 6. backend parity ---------------------------------------------------------------

def _scenario(repo):
    t, clock = world(repo)
    _recurring(t)
    t.as_user("bob").create_issue("WEB", "Backup check", due="2026-04-27", recurrence="every week")
    t.as_user("bob").add_comment("WEB-2", "ping @ana")
    clock.advance(86400)
    t.as_user("bob").close("WEB-2")
    t.as_user("bob").close("WEB-1")
    with pytest.raises(ValidationError):
        t.bulk_transition(["WEB-4", "WEB-1"], "done")
    t.set_recurrence("WEB-4", "every 3 weeks on tue,fri")
    t.as_user("ana").set_recurrence("WEB-3", "")
    t.import_issues("WEB", [{"title": "Imported", "due": "2026-06-30", "recurrence": "every month on last"}])
    t.bulk_transition(["WEB-5", "WEB-4"], "done")
    t.reopen("WEB-1")
    t.close("WEB-1")
    return dump(repo)


def test_backends_behave_identically(tmp_path):
    a = _scenario(make_repo("json"))
    b = _scenario(make_repo("sqlite"))
    assert a == b
    assert [i["key"] if "key" in i else f"{i['project']}-{i['number']}" for i in a["issues"]] == \
        ["WEB-1", "WEB-2", "WEB-3", "WEB-4", "WEB-5", "WEB-6", "WEB-7"]


def test_backends_identical_after_reopen(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    a = _scenario(make_repo("json", tmp_path / "a"))
    b = _scenario(make_repo("sqlite", tmp_path / "b"))
    assert dump(open_repository(tmp_path / "a" / "h.json")) == a
    assert dump(open_repository(tmp_path / "b" / "h.db")) == b == a


# ---- 7. old data ------------------------------------------------------------------------

@pytest.mark.parametrize("version", [1, 2, 3, 4])
@pytest.mark.parametrize("ext", ["json", "db"])
def test_old_fixtures_open_and_upgrade(tmp_path, version, ext):
    path = copy_fixture(tmp_path, version, ext)
    repo = open_repository(path)
    assert repo.opened_version == version
    assert repo.schema_version == 5
    issues = {i.key: i for i in repo.list_issues()}
    assert sorted(issues) == ["APP-10", "APP-2", "APP-5", "INFRA-1", "INFRA-2"]
    assert all(i.recurrence == "" and i.spawned_from == "" for i in issues.values())
    assert issues["APP-2"].labels == ("crash", "ios")
    assert issues["APP-2"].due == "2024-11-20"
    assert repo.get_membership("APP", "gus").role == "viewer"
    assert repo.peek_comment_id() == 6


def test_old_fixtures_all_equal(tmp_path):
    dumps = [dump(open_repository(copy_fixture(tmp_path, v, ext))) for v in (1, 2, 3, 4)
             for ext in ("json", "db")]
    assert all(d == dumps[0] for d in dumps)


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_old_json_written_back_as_v5(tmp_path, version):
    path = copy_fixture(tmp_path, version, "json")
    raw = path.read_bytes()
    repo = JsonFileRepository(path)
    assert path.read_bytes() == raw
    t = Tracker(repo, clock=FixedClock("2024-12-01T09:00:00Z"))
    t.set_recurrence("APP-2", "every week")
    doc = json.loads(path.read_text())
    assert doc["version"] == 5
    assert all("recurrence" in i and "spawned_from" in i for i in doc["issues"])
    assert JsonFileRepository(path).get_issue("APP", 2).recurrence == "every week on wed"


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_old_sqlite_upgraded_on_open(tmp_path, version):
    path = copy_fixture(tmp_path, version, "db")
    SqliteRepository(str(path)).close()
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
    cols = [r[1] for r in conn.execute("PRAGMA table_info(issues)")]
    conn.close()
    assert cols[-2:] == ["recurrence", "spawned_from"]
    fresh = SqliteRepository(":memory:")
    old = SqliteRepository(str(path))
    assert old.table_names() == fresh.table_names()
    for table in fresh.table_names():
        assert old.table_columns(table) == fresh.table_columns(table), table


def test_old_sqlite_full_cycle(tmp_path):
    path = copy_fixture(tmp_path, 1, "db")
    repo = SqliteRepository(str(path))
    t = Tracker(repo, actor="dee", clock=FixedClock("2024-11-25T09:00:00Z"))
    t.set_recurrence("APP-2", "every 2 weeks on mon")
    t.close("APP-2")
    repo.close()
    again = SqliteRepository(str(path))
    new = again.get_issue("APP", 11)
    assert (new.spawned_from, new.due, new.assignee) == ("APP-2", "2024-12-02", "fay")
    assert again.get_issue("APP", 2).recurrence == "every 2 weeks on mon"


def test_v5_newer_refused(tmp_path):
    p = tmp_path / "future.json"
    p.write_text(json.dumps({"format": "trellis", "version": 6}))
    with pytest.raises(StorageError):
        JsonFileRepository(p)
    db = tmp_path / "future.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE x (a)")
    conn.execute("PRAGMA user_version = 6")
    conn.commit()
    conn.close()
    with pytest.raises(StorageError):
        SqliteRepository(str(db))


def test_v5_json_loads_as_is(tmp_path):
    p = tmp_path / "five.json"
    repo = JsonFileRepository(p)
    t, _ = world(repo)
    _recurring(t)
    raw = p.read_bytes()
    again = JsonFileRepository(p)
    assert again.opened_version == 5
    again.commit()
    assert p.read_bytes() == raw


# ---- 8. query language ----------------------------------------------------------------

def _qissues():
    return [
    Issue("WEB", 1, "a", due="2026-05-04", recurrence="every week on mon"),
    Issue("WEB", 2, "b", due="2026-05-11", recurrence="every week on mon", spawned_from="WEB-1"),
    Issue("WEB", 3, "c", due="2026-05-31", recurrence="every month on 31"),
    Issue("WEB", 4, "d", due="2026-05-06"),
    Issue("WEB", 5, "e", spawned_from="WEB-3"),
    ]


@pytest.mark.parametrize("query,expected", [
    ("recurring", ["WEB-1", "WEB-2", "WEB-3"]),
    ("not recurring", ["WEB-4", "WEB-5"]),
    ("recurring = false", ["WEB-4", "WEB-5"]),
    ("recurring and due < 2026-05-10", ["WEB-1"]),
    ("repeats ~ month", ["WEB-3"]),
    ("recurrence ~ WEEK", ["WEB-1", "WEB-2"]),
    ("recurrence = 'every week on mon'", ["WEB-1", "WEB-2"]),
    ("recurrence = ''", ["WEB-4", "WEB-5"]),
    ("spawned", ["WEB-2", "WEB-5"]),
    ("not spawned and recurring", ["WEB-1", "WEB-3"]),
    ("previous = web-1", ["WEB-2"]),
    ("spawned_from in (WEB-3, WEB-9)", ["WEB-5"]),
    ("spawned_from ~ 3", ["WEB-5"]),
])
def test_query_fields(query, expected):
    assert [i.key for i in filter_issues(_qissues(), query, "2026-05-04")] == expected


@pytest.mark.parametrize("query", ["recurring > 1", "repeats < x", "spawned ~ x", "previous >= WEB-1"])
def test_query_bad_operators(query):
    with pytest.raises(QueryError):
        filter_issues(_qissues(), query, "2026-05-04")


def test_search_uses_new_fields(env):
    t, _ = env
    _recurring(t)
    t.close("WEB-1")
    assert [i.key for i in t.search("spawned")] == ["WEB-2"]
    assert [i.key for i in t.search("recurring and open")] == ["WEB-2"]


# ---- 9. CLI -------------------------------------------------------------------------

def _seed(db):
    ok(db, "create", "WEB", "Weekly report", "-a", "bob", "--due", "today", "--repeat",
       "every 2 weeks on mon,thu", "-l", "ops", user="ana")
    ok(db, "create", "WEB", "One-off", "--due", "+2d", user="bob")


def test_cli_create_repeat_and_show(db):
    _seed(db)
    out = ok(db, "show", "WEB-1")
    lines = out.splitlines()
    i = lines.index("Due:        2026-05-04")
    assert lines[i + 1] == "Repeats:    every 2 weeks on mon,thu"
    assert lines[i + 2] == "Estimate:   -"
    assert not any(line.startswith("Previous:") for line in lines)
    lines = ok(db, "show", "WEB-2").splitlines()
    assert lines[lines.index("Due:        2026-05-06") + 1] == "Repeats:    -"


def test_cli_create_repeat_needs_due(db):
    rc, out, err = run(db, "create", "WEB", "x", "--repeat", "every day", user="ana")
    assert rc == 1 and err.startswith("error: ")
    rc, out, err = run(db, "create", "WEB", "x", "--due", "today", "--repeat", "every blue moon",
                       user="ana")
    assert rc == 1 and err.startswith("error: ")
    assert ok(db, "list", "-f", "json") == "[]\n"


def test_cli_repeat_command(db):
    _seed(db)
    assert ok(db, "repeat", "WEB-2", "every week", user="bob") == "WEB-2: repeats every week on wed\n"
    assert ok(db, "repeat", "web-2", "none", user="bob") == "WEB-2: does not repeat\n"
    assert ok(db, "repeat", "WEB-2", "-", user="bob") == "WEB-2: does not repeat\n"
    rc, _, err = run(db, "repeat", "WEB-2", "every week", user="cyd")
    assert rc == 1 and err.startswith("error: ")
    rc, _, err = run(db, "repeat", "WEB-1", "every day", user="cyd")
    assert rc == 1


def test_cli_close_prints_spawn(db):
    _seed(db)
    assert ok(db, "close", "WEB-1", user="bob") == "WEB-1: done\nspawned WEB-3 due 2026-05-07\n"
    assert ok(db, "reopen", "WEB-1", user="bob") == "WEB-1: open\n"
    assert ok(db, "close", "WEB-1", user="bob") == "WEB-1: done\n"
    assert ok(db, "move", "WEB-3", "in-progress", user="bob") == "WEB-3: in_progress\n"
    assert ok(db, "move", "WEB-3", "done", user="bob") == "WEB-3: done\nspawned WEB-4 due 2026-05-18\n"
    assert ok(db, "close", "WEB-2", user="bob") == "WEB-2: done\n"
    lines = ok(db, "show", "WEB-4").splitlines()
    i = lines.index("Due:        2026-05-18")
    assert lines[i + 1:i + 3] == ["Repeats:    every 2 weeks on mon,thu", "Previous:   WEB-3"]


def test_cli_series_ended(db):
    ok(db, "create", "WEB", "Last one", "--due", "today", "--repeat", "every day until 2026-05-04",
       user="ana")
    assert ok(db, "close", "WEB-1", "--wontfix", user="ana") == "WEB-1: wontfix\nWEB-1: series ended\n"
    assert ok(db, "reopen", "WEB-1") == "WEB-1: open\n"


def test_cli_bulk_move_prints_spawns_in_order(db):
    _seed(db)
    ok(db, "create", "WEB", "Monthly", "--due", "2026-05-31", "--repeat", "every month", user="ana")
    assert ok(db, "bulk", "move", "done", "WEB-3", "WEB-2", "WEB-1") == (
        "moved 3 issue(s) to done\n"
        "spawned WEB-4 due 2026-06-30\n"
        "spawned WEB-5 due 2026-05-07\n"
    )


def test_cli_show_json(db):
    _seed(db)
    ok(db, "close", "WEB-1")
    obj = json.loads(ok(db, "show", "WEB-3", "--json"))
    assert (obj["recurrence"], obj["spawned_from"]) == ("every 2 weeks on mon,thu", "WEB-1")
    keys = list(obj)
    assert keys[keys.index("closed_at") + 1:keys.index("closed_at") + 3] == ["recurrence", "spawned_from"]


def test_cli_export_csv(db):
    _seed(db)
    ok(db, "close", "WEB-1")
    rows = list(csv.reader(io.StringIO(ok(db, "export", "issues"))))
    assert rows[0] == ["key", "project", "number", "title", "type", "status", "priority", "assignee",
                       "reporter", "labels", "watchers", "due", "estimate", "created", "updated",
                       "closed", "recurrence", "spawned_from"]
    assert rows[1][-2:] == ["every 2 weeks on mon,thu", ""]
    assert rows[2][-2:] == ["", ""]
    assert rows[3][0] == "WEB-3" and rows[3][-2:] == ["every 2 weeks on mon,thu", "WEB-1"]


def test_cli_export_json(db):
    _seed(db)
    data = json.loads(ok(db, "export", "issues", "-f", "json"))
    assert list(data[0]) == ["key", "project", "number", "title", "description", "type", "status",
                             "priority", "assignee", "reporter", "labels", "watchers", "due",
                             "estimate", "created_at", "updated_at", "closed_at", "recurrence",
                             "spawned_from"]
    assert data[0]["recurrence"] == "every 2 weeks on mon,thu" and data[1]["spawned_from"] == ""


def test_cli_export_table_unchanged(db):
    _seed(db)
    assert ok(db, "list") == (
        "Key    Type  Status  Pri     Assignee  Due         Title\n"
        "-----  ----  ------  ------  --------  ----------  -------------\n"
        "WEB-1  task  open    normal  bob       2026-05-04  Weekly report\n"
        "WEB-2  task  open    normal  -         2026-05-06  One-off\n"
        "\n"
        "2 issues (2 open)\n"
    )


def test_cli_list_where(db):
    _seed(db)
    ok(db, "close", "WEB-1")
    out = ok(db, "list", "-w", "recurring and open", "-f", "csv")
    assert [r[0] for r in csv.reader(io.StringIO(out))][1:] == ["WEB-3"]
    out = ok(db, "list", "-w", "previous = WEB-1", "-f", "csv")
    assert [r[0] for r in csv.reader(io.StringIO(out))][1:] == ["WEB-3"]


def test_cli_export_import_roundtrip(db, tmp_path):
    _seed(db)
    ok(db, "close", "WEB-1")
    f = tmp_path / "x.csv"
    ok(db, "export", "issues", "-w", "open", "-o", str(f))
    assert ok(db, "import", "WEB", str(f), user="ana") == "imported 2 issue(s): WEB-4 .. WEB-5\n"
    data = {d["key"]: d for d in json.loads(ok(db, "export", "issues", "-f", "json"))}
    assert data["WEB-5"]["recurrence"] == "every 2 weeks on mon,thu"
    assert data["WEB-5"]["spawned_from"] == ""
    assert data["WEB-4"]["recurrence"] == ""


def test_cli_import_recurrence_column(db, tmp_path):
    f = tmp_path / "in.csv"
    f.write_text("title,due,recurrence,spawned_from\n"
                 "Pay rent,2026-05-31,Every Month,WEB-77\n"
                 "Plain,,,\n")
    assert ok(db, "import", "WEB", str(f), user="ana") == "imported 2 issue(s): WEB-1 .. WEB-2\n"
    data = json.loads(ok(db, "export", "issues", "-f", "json"))
    assert [(d["recurrence"], d["spawned_from"]) for d in data] == [("every month on 31", ""), ("", "")]
    bad = tmp_path / "bad.csv"
    bad.write_text("title,recurrence\nNo due,every day\n")
    rc, _, err = run(db, "import", "WEB", str(bad), user="ana")
    assert rc == 1 and "row 1" in err


def test_cli_agenda(db):
    _seed(db)
    assert ok(db, "agenda") == (
        "Key    Due          In  Status  Assignee  Repeats                   Title\n"
        "-----  ----------  ---  ------  --------  ------------------------  -------------\n"
        "WEB-1  2026-05-04  +0d  open    bob       every 2 weeks on mon,thu  Weekly report\n"
        "WEB-2  2026-05-06  +2d  open    -         -                         One-off\n"
    )


def test_cli_report_due(db):
    _seed(db)
    assert ok(db, "report", "due") == (
        "Today (1)\n"
        "Key    Due          In  Assignee  Repeats                   Title\n"
        "-----  ----------  ---  --------  ------------------------  -------------\n"
        "WEB-1  2026-05-04  +0d  bob       every 2 weeks on mon,thu  Weekly report\n"
        "\n"
        "This week (1)\n"
        "Key    Due          In  Assignee  Repeats  Title\n"
        "-----  ----------  ---  --------  -------  -------\n"
        "WEB-2  2026-05-06  +2d  -         -        One-off\n"
    )


def test_cli_report_recurring(db):
    assert ok(db, "report", "recurring") == "No recurring issues.\n"
    _seed(db)
    ok(db, "create", "WEB", "Old chore", "--due", "2026-04-01", "--repeat", "every month on last",
       user="ana")
    ok(db, "create", "WEB", "Ending", "--due", "2026-05-05", "--repeat", "every week until 2026-05-10",
       user="ana")
    ok(db, "create", "WEB", "Closed one", "--due", "2026-05-01", "--repeat", "every day", user="ana")
    assert ok(db, "close", "WEB-5", user="ana") == "WEB-5: done\nspawned WEB-6 due 2026-05-04\n"
    expected = (
        "Key    Due         Rule                                Next        Assignee\n"
        "-----  ----------  ----------------------------------  ----------  --------\n"
        "WEB-3  2026-04-01  every month on last                 2026-05-31  -\n"
        "WEB-1  2026-05-04  every 2 weeks on mon,thu            2026-05-07  bob\n"
        "WEB-6  2026-05-04  every day                           2026-05-05  -\n"
        "WEB-4  2026-05-05  every week on tue until 2026-05-10  ends        -\n"
    )
    assert ok(db, "report", "recurring") == expected
    assert ok(db, "report", "recurring", "-P", "WEB") == expected
    # a reader sees the same; an outsider is refused
    assert ok(db, "report", "recurring", user="cyd") == expected


def test_cli_digest_marks_recurring(db, monkeypatch):
    _seed(db)
    ok(db, "assign", "WEB-2", "bob")
    out = ok(db, "digest", user="bob")
    assert "  WEB-1  due 2026-05-04 (today)  Weekly report  (repeats)\n" in out
    assert "  WEB-2  due 2026-05-06 (in 2d)  One-off\n" in out
    monkeypatch.setenv("TRELLIS_NOW", "2026-05-08T09:00:00Z")
    out = ok(db, "digest", user="bob")
    assert "Overdue (2)\n  WEB-1  due 2026-05-04 (4d ago)  Weekly report  (repeats)\n" in out


def test_cli_timeline(db):
    _seed(db)
    ok(db, "repeat", "WEB-2", "every day", user="bob")
    ok(db, "repeat", "WEB-2", "none", user="ana")
    ok(db, "close", "WEB-1", user="bob")
    assert ok(db, "show", "WEB-2", "--timeline") == (
        "2026-05-04T09:00:00Z  bob created the issue\n"
        "2026-05-04T09:00:00Z  bob set the recurrence to every day\n"
        "2026-05-04T09:00:00Z  ana cleared the recurrence\n"
    )
    assert ok(db, "show", "WEB-3", "--timeline") == \
        "2026-05-04T09:00:00Z  bob created the issue (spawned from WEB-1)\n"


def test_cli_history_shows_recurrence_events(db):
    _seed(db)
    ok(db, "repeat", "WEB-2", "every day", user="bob")
    out = ok(db, "history", "--subject", "WEB-2", "--action", "issue.recurrence_changed")
    assert out == ("#10 2026-05-04T09:00:00Z bob issue.recurrence_changed WEB-2 "
                   "from='' to='every day'\n")


def test_cli_db_info_and_check(db):
    _seed(db)
    assert "Version:   5\n" in ok(db, "db", "info")
    assert ok(db, "db", "check") == "ok\n"


@pytest.mark.parametrize("bad,message", [
    (dict(recurrence="every day", due=""), "WEB-1: recurring but has no due date"),
    (dict(recurrence="every week", due="2026-05-04"), "WEB-1: recurrence 'every week' is not canonical"),
    (dict(recurrence="every week on thu,mon", due="2026-05-04"),
     "WEB-1: recurrence 'every week on thu,mon' is not canonical"),
    (dict(recurrence="whenever", due="2026-05-04"), "WEB-1: recurrence 'whenever' is not canonical"),
])
def test_cli_db_check_recurrence_problems(db, bad, message):
    from dataclasses import replace
    ok(db, "create", "WEB", "x", "--due", "today")
    repo = open_repository(db)
    repo.save_issue(replace(repo.get_issue("WEB", 1), **bad))
    repo.commit()
    repo.close()
    rc, out, _ = run(db, "db", "check")
    assert rc == 1
    assert out == f"{message}\n1 problem(s)\n"


def test_cli_db_upgrade_old_json(tmp_path):
    path = copy_fixture(tmp_path, 3, "json")
    assert "On disk:   3" in ok(path, "db", "info")
    assert ok(path, "db", "upgrade") == "upgraded from version 3 to 5\n"
    assert json.loads(path.read_text())["version"] == 5
    assert ok(path, "db", "upgrade") == "already at version 5\n"


def test_cli_db_copy_preserves_recurrence(db, tmp_path):
    _seed(db)
    ok(db, "close", "WEB-1")
    dest = tmp_path / ("copy.db" if str(db).endswith(".json") else "copy.json")
    out = ok(db, "db", "copy", str(dest))
    assert "WARNING" not in out
    assert dump(open_repository(dest)) == dump(open_repository(db))


# ---- 10. existing behaviour still works ----------------------------------------------

def test_existing_events_unchanged(env):
    t, _ = env
    t.create_issue("WEB", "x", assignee="bob", labels=["a"], estimate=1)
    t.transition("WEB-1", "done")
    evs = t.audit.events(subject="WEB-1")
    assert evs[0].details == {"title": "x", "type": "task", "priority": "normal", "assignee": "bob",
                              "labels": ["a"], "estimate": 1}
    assert [e.action for e in evs] == ["issue.created", "issue.transitioned"]


def test_existing_cli_outputs(db):
    ok(db, "create", "WEB", "Plain", "--due", "2026-05-01", "-a", "bob", user="ana")
    assert ok(db, "assign", "WEB-1", "-") == "WEB-1: assigned to nobody\n"
    assert ok(db, "label", "WEB-1", "X", "y") == "WEB-1: labels x, y\n"
    assert ok(db, "close", "WEB-1") == "WEB-1: done\n"
    assert ok(db, "agenda") == "nothing due\n"
    assert ok(db, "report", "due") == "Nothing due.\n"
    assert ok(db, "move", "WEB-1", "open") == "WEB-1: open\n"
    assert ok(db, "report", "labels", "-P", "WEB") == (
        "Label  Open  Total\n"
        "-----  ----  -----\n"
        "x         1      1\n"
        "y         1      1\n"
    )


def test_existing_query_fields_still_work():
    issues = [Issue("WEB", 1, "Fix login", labels=("auth",), due="2026-05-01", priority="high"),
              Issue("WEB", 2, "Docs", priority="low")]
    assert [i.key for i in filter_issues(issues, "overdue or pri < normal", "2026-05-04")] == \
        ["WEB-1", "WEB-2"]
    assert [i.key for i in filter_issues(issues, "tag = auth", "2026-05-04")] == ["WEB-1"]
