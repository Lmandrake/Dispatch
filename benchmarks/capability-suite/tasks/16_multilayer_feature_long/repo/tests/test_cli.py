import json

import pytest

from tests.helpers import run_cli


@pytest.fixture(params=["json", "db"])
def db(request, tmp_path):
    path = tmp_path / f"t.{request.param}"
    steps = [
        ("user", "add", "ana", "Ana Lima", "--email", "ana@example.com"),
        ("user", "add", "bob", "Bob Stone"),
        ("project", "create", "WEB", "Website", "--lead", "ana"),
        ("member", "add", "WEB", "bob", "member"),
    ]
    for argv in steps:
        rc, out, err = run_cli(path, *argv)
        assert rc == 0, err
    assert run_cli(path, "create", "WEB", "Login broken", "-t", "bug", "-p", "urgent", "-a", "bob",
                   "--due", "+3d", "-l", "auth", "-l", "UI", "-e", "3", user="ana")[0] == 0
    assert run_cli(path, "create", "WEB", "Write docs", "--due", "2026-04-28", user="bob")[0] == 0
    return path


def test_show(db):
    rc, out, _ = run_cli(db, "show", "web-1")
    assert rc == 0
    assert out.splitlines()[:15] == [
        "WEB-1  Login broken",
        "Project:    WEB",
        "Type:       bug",
        "Status:     open",
        "Priority:   urgent",
        "Reporter:   ana",
        "Assignee:   bob",
        "Labels:     auth, ui",
        "Watchers:   ana",
        "Due:        2026-05-04",
        "Estimate:   3",
        "Created:    2026-05-01T09:00:00Z",
        "Updated:    2026-05-01T09:00:00Z",
        "Closed:     -",
    ][:15]


def test_move_close_reopen(db):
    assert run_cli(db, "move", "WEB-1", "in-progress", user="bob")[1] == "WEB-1: in_progress\n"
    assert run_cli(db, "close", "WEB-1", user="bob")[1] == "WEB-1: done\n"
    assert run_cli(db, "reopen", "WEB-1", user="bob")[1] == "WEB-1: open\n"
    assert run_cli(db, "bulk", "move", "done", "WEB-1", "WEB-2")[1] == "moved 2 issue(s) to done\n"


def test_errors(db):
    rc, _, err = run_cli(db, "create", "WEB", "nope", user="nobody")
    assert rc == 1 and err == "error: no such user: nobody\n"
    rc, _, err = run_cli(db, "list", "--where", "due <")
    assert rc == 1 and "expected a value" in err
    rc, _, _ = run_cli(db, "move", "WEB-1", "sideways")
    assert rc == 2


def test_list_table(db):
    rc, out, _ = run_cli(db, "list")
    assert out == (
        "Key    Type  Status  Pri     Assignee  Due         Title\n"
        "-----  ----  ------  ------  --------  ----------  ------------\n"
        "WEB-1  bug   open    urgent  bob       2026-05-04  Login broken\n"
        "WEB-2  task  open    normal  -         2026-04-28  Write docs\n"
        "\n"
        "2 issues (2 open)\n"
    )


def test_agenda(db):
    rc, out, _ = run_cli(db, "agenda")
    assert out == (
        "Key    Due          In  Status  Assignee  Title\n"
        "-----  ----------  ---  ------  --------  ------------\n"
        "WEB-2  2026-04-28  -3d  open    -         Write docs\n"
        "WEB-1  2026-05-04  +3d  open    bob       Login broken\n"
    )
    assert run_cli(db, "agenda", "--days", "1", "--user", "ana")[1] == "nothing due\n"


def test_report_due(db):
    rc, out, _ = run_cli(db, "report", "due")
    assert out == (
        "Overdue (1)\n"
        "Key    Due          In  Assignee  Title\n"
        "-----  ----------  ---  --------  ----------\n"
        "WEB-2  2026-04-28  -3d  -         Write docs\n"
        "\n"
        "Later (1)\n"
        "Key    Due          In  Assignee  Title\n"
        "-----  ----------  ---  --------  ------------\n"
        "WEB-1  2026-05-04  +3d  bob       Login broken\n"
    )


def test_digest(db):
    run_cli(db, "move", "WEB-1", "in_progress", user="bob")
    run_cli(db, "comment", "WEB-1", "on it @ana", user="bob")
    rc, out, _ = run_cli(db, "digest", "--mark", user="ana")
    assert out == (
        "Digest for ana (2026-05-01)\n"
        "\n"
        "Watching (1)\n"
        "  #8 bob issue.transitioned WEB-1 from='open' to='in_progress'\n"
        "\n"
        "Mentions (1)\n"
        "  #9 bob WEB-1: comment 1\n"
    )
    assert run_cli(db, "digest", user="ana")[1] == "Digest for ana (2026-05-01)\n\nNothing new.\n"
    rc, out, _ = run_cli(db, "digest", user="bob")
    assert out.splitlines()[2:4] == ["Due soon (1)", "  WEB-1  due 2026-05-04 (in 3d)  Login broken"]
    run_cli(db, "assign", "WEB-2", "bob", user="bob")
    rc, out, _ = run_cli(db, "digest", user="bob")
    assert out.splitlines()[2:7] == ["Overdue (1)", "  WEB-2  due 2026-04-28 (3d ago)  Write docs", "",
                                     "Due soon (1)", "  WEB-1  due 2026-05-04 (in 3d)  Login broken"]


def test_export_csv_and_json(db):
    rc, out, _ = run_cli(db, "export", "issues", "-w", "type = bug")
    assert out.splitlines() == [
        "key,project,number,title,type,status,priority,assignee,reporter,labels,watchers,due,"
        "estimate,created,updated,closed",
        "WEB-1,WEB,1,Login broken,bug,open,urgent,bob,ana,auth;ui,ana,2026-05-04,3,"
        "2026-05-01T09:00:00Z,2026-05-01T09:00:00Z,",
    ]
    rc, out, _ = run_cli(db, "export", "issues", "-f", "json")
    data = json.loads(out)
    assert list(data[0]) == ["key", "project", "number", "title", "description", "type", "status",
                             "priority", "assignee", "reporter", "labels", "watchers", "due",
                             "estimate", "created_at", "updated_at", "closed_at"]


def test_export_import_roundtrip(db, tmp_path):
    out_file = tmp_path / "issues.csv"
    assert run_cli(db, "export", "issues", "-o", str(out_file))[0] == 0
    rc, out, err = run_cli(db, "import", "WEB", str(out_file), user="ana")
    assert (rc, out) == (0, "imported 2 issue(s): WEB-3 .. WEB-4\n"), err
    rc, out, _ = run_cli(db, "show", "WEB-3", "--json")
    obj = json.loads(out)
    assert (obj["title"], obj["labels"], obj["due"], obj["estimate"]) == \
        ("Login broken", ["auth", "ui"], "2026-05-04", 3)


def test_history_and_timeline(db):
    run_cli(db, "assign", "WEB-2", "ana", user="bob")
    rc, out, _ = run_cli(db, "history", "--subject", "WEB-2")
    assert out.splitlines() == [
        "#7 2026-05-01T09:00:00Z bob issue.created WEB-2 due='2026-04-28' priority='normal' "
        "title='Write docs' type='task'",
        "#8 2026-05-01T09:00:00Z bob issue.assigned WEB-2 from='' to='ana'",
    ]
    rc, out, _ = run_cli(db, "show", "WEB-2", "--timeline")
    assert out == ("2026-05-01T09:00:00Z  bob created the issue\n"
                   "2026-05-01T09:00:00Z  bob assigned it to ana\n")


def test_db_info_and_check(db):
    rc, out, _ = run_cli(db, "db", "info")
    assert "Version:   4" in out
    assert run_cli(db, "db", "check")[1] == "ok\n"


def test_explain(db):
    rc, out, _ = run_cli(db, "explain", "pri >= high or due < today")
    assert out == ("query:  (priority >= high or due < today)\n"
                   "fields: due (date), priority (enum)\n"
                   "matches: 2\n")
