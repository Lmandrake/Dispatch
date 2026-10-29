# NOTE: all people, handles and ticket/incident numbers in this generator are FICTIONAL test data.
"""Generate old-version fixtures for task 16 (trellis recurring issues).

Writes, for each dataset (repo: tests/data/, hidden: hidden/):
  <prefix>v1.json .. v4.json   JSON data files in format versions 1..4
  <prefix>v1.db   .. v4.db     SQLite databases at schema versions 1..4
Older versions are built the way trellis 0.5 wrote them (v1), then the
start repo's own migration steps produce v2..v4.
"""
import copy, json, os, sqlite3, sys

# The working copy the suite was frozen from (harnesses/bench/tasks), as capability_bench reads it.
TASK = os.path.join(os.environ.get("NH_TASKS_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "harnesses", "bench", "tasks"),
    "16_multilayer_feature_long")
sys.path.insert(0, TASK + "/repo")
from trellis.storage import json_migrations as JM
from trellis.storage import sqlite_migrations as SM

DATASETS = {
    "repo": dict(
        out=TASK + "/repo/tests/data", prefix="legacy_",
        users=[("ana", "Ana Lima", "ana@example.com", "2025-01-02T08:00:00Z"),
               ("bob", "Bob Stone", "", "2025-01-02T08:05:00Z"),
               ("cyd", "Cyd Park", "cyd@example.com", "2025-01-03T10:00:00Z")],
        projects=[("WEB", "Website", "Public site", 4, "2025-01-02T09:00:00Z"),
                  ("OPS", "Operations", "", 2, "2025-01-04T09:00:00Z")],
        members=[("WEB", "ana", "owner"), ("WEB", "bob", "writer"), ("WEB", "cyd", "reader"),
                 ("OPS", "bob", "owner")],
        issues=[
            dict(project="WEB", number=1, title="Login page broken", description="500 on submit",
                 type="bug", status="done", priority="urgent", reporter="ana", assignee="bob",
                 tags="UI, auth", deadline="2025-01-10", created_at="2025-01-05T10:00:00Z",
                 updated_at="2025-01-08T16:00:00Z", closed_at="2025-01-08T16:00:00Z",
                 comments=[("bob", "Looking at it", "2025-01-06T09:00:00Z"),
                           ("ana", "Thanks @bob", "2025-01-06T09:30:00Z")]),
            dict(project="WEB", number=2, title="Write style guide", description="",
                 type="task", status="open", priority="normal", reporter="bob", assignee="",
                 tags="docs", deadline="", created_at="2025-01-06T11:00:00Z",
                 updated_at="2025-01-06T11:00:00Z", closed_at="", comments=[]),
            dict(project="WEB", number=3, title="Renew TLS certificate", description="",
                 type="chore", status="in_progress", priority="high", reporter="ana", assignee="ana",
                 tags="", deadline="2025-02-01", created_at="2025-01-07T12:00:00Z",
                 updated_at="2025-01-07T12:30:00Z", closed_at="",
                 comments=[("ana", "Ordered", "2025-01-07T12:30:00Z")]),
            dict(project="OPS", number=1, title="Rotate backup tapes", description="weekly",
                 type="chore", status="open", priority="low", reporter="bob", assignee="bob",
                 tags="ops,Backups", deadline="2025-01-12", created_at="2025-01-04T09:30:00Z",
                 updated_at="2025-01-04T09:30:00Z", closed_at="", comments=[]),
        ],
        events=[(1, "2025-01-02T09:00:00Z", "project.created", "WEB", {"name": "Website"}),
                (2, "2025-01-05T10:00:00Z", "issue.created", "WEB-1",
                 {"title": "Login page broken", "type": "bug", "priority": "urgent"}),
                (3, "2025-01-08T16:00:00Z", "issue.transitioned", "WEB-1", {"from": "open", "to": "done"})],
    ),
    "hidden": dict(
        out=TASK + "/hidden", prefix="hidden_fixture_",
        users=[("dee", "Dee Ortiz", "dee@example.org", "2024-11-01T08:00:00Z"),
               ("eli", "Eli Brandt", "eli@example.org", "2024-11-01T08:01:00Z"),
               ("fay", "Fay Chen", "", "2024-11-02T08:00:00Z"),
               ("gus", "Gus Moe", "", "2024-11-02T08:30:00Z")],
        projects=[("APP", "Mobile app", "iOS and Android", 11, "2024-11-01T09:00:00Z"),
                  ("INFRA", "Infrastructure", "", 3, "2024-11-03T09:00:00Z")],
        members=[("APP", "dee", "owner"), ("APP", "eli", "writer"), ("APP", "fay", "writer"),
                 ("APP", "gus", "reader"), ("INFRA", "eli", "owner"), ("INFRA", "dee", "writer")],
        issues=[
            dict(project="APP", number=2, title="Crash on launch", description="iOS 17 only",
                 type="bug", status="open", priority="urgent", reporter="eli", assignee="fay",
                 tags="ios, Crash ,ios", deadline="2024-11-20", created_at="2024-11-05T10:00:00Z",
                 updated_at="2024-11-05T10:00:00Z", closed_at="",
                 comments=[("fay", "Repro'd", "2024-11-05T11:00:00Z")]),
            dict(project="APP", number=10, title="Dark mode", description="",
                 type="story", status="review", priority="normal", reporter="dee", assignee="eli",
                 tags="ui", deadline="", created_at="2024-11-06T10:00:00Z",
                 updated_at="2024-11-09T10:00:00Z", closed_at="",
                 comments=[("dee", "Looks good", "2024-11-09T10:00:00Z"),
                           ("eli", "Merging @dee", "2024-11-09T11:00:00Z"),
                           ("gus", "nice", "2024-11-09T12:00:00Z")]),
            dict(project="APP", number=5, title="Monthly dependency bump", description="",
                 type="chore", status="done", priority="low", reporter="dee", assignee="dee",
                 tags="", deadline="2024-11-30", created_at="2024-11-07T10:00:00Z",
                 updated_at="2024-11-29T10:00:00Z", closed_at="2024-11-29T10:00:00Z", comments=[]),
            dict(project="INFRA", number=1, title="Patch kernel", description="",
                 type="task", status="blocked", priority="high", reporter="eli", assignee="dee",
                 tags="security", deadline="2024-12-01", created_at="2024-11-03T10:00:00Z",
                 updated_at="2024-11-04T10:00:00Z", closed_at="", comments=[]),
            dict(project="INFRA", number=2, title="Audit firewall rules", description="",
                 type="task", status="wontfix", priority="normal", reporter="eli", assignee="",
                 tags="security,network", deadline="", created_at="2024-11-03T11:00:00Z",
                 updated_at="2024-11-04T11:00:00Z", closed_at="2024-11-04T11:00:00Z",
                 comments=[("eli", "Out of scope", "2024-11-04T11:00:00Z")]),
        ],
        events=[(1, "2024-11-01T09:00:00Z", "project.created", "APP", {"name": "Mobile app"}),
                (2, "2024-11-03T09:00:00Z", "project.created", "INFRA", {"name": "Infrastructure"}),
                (3, "2024-11-05T10:00:00Z", "issue.created", "APP-2",
                 {"title": "Crash on launch", "type": "bug", "priority": "urgent"}),
                (4, "2024-11-29T10:00:00Z", "issue.transitioned", "APP-5", {"from": "open", "to": "done"})],
    ),
}


def json_v1(ds):
    return {
        "version": 1,
        "users": [dict(username=u, display_name=n, email=e, created_at=c) for u, n, e, c in ds["users"]],
        "projects": [dict(key=k, name=n, description=d, next_number=nn, created_at=c)
                     for k, n, d, nn, c in ds["projects"]],
        "memberships": [dict(project=p, username=u, role=r) for p, u, r in ds["members"]],
        "issues": [dict({k: v for k, v in i.items() if k != "comments"},
                        comments=[dict(author=a, body=b, created_at=c) for a, b, c in i["comments"]])
                   for i in ds["issues"]],
        "events": [dict(seq=s, timestamp=t, action=a, subject=su, details=d) for s, t, a, su, d in ds["events"]],
    }


def sqlite_v1(path, ds):
    if os.path.exists(path):
        os.unlink(path)
    conn = sqlite3.connect(path, isolation_level=None)
    SM.create(conn, SM.V1_SCHEMA, version=1)
    conn.execute("BEGIN")
    for u in ds["users"]:
        conn.execute("INSERT INTO users VALUES (?,?,?,?)", u)
    for p in ds["projects"]:
        conn.execute("INSERT INTO projects VALUES (?,?,?,?,?)", p)
    for m in ds["members"]:
        conn.execute("INSERT INTO members VALUES (?,?,?)", m)
    for i in ds["issues"]:
        conn.execute("INSERT INTO issues (project, number, title, description, type, status, priority, "
                     "reporter, assignee, tags, deadline, created_at, updated_at, closed_at) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (i["project"], i["number"], i["title"], i["description"], i["type"], i["status"],
                      i["priority"], i["reporter"], i["assignee"], i["tags"], i["deadline"],
                      i["created_at"], i["updated_at"], i["closed_at"]))
    for i in sorted(ds["issues"], key=lambda i: (i["project"], i["number"])):
        for a, b, c in i["comments"]:
            conn.execute("INSERT INTO comments (issue_key, author, body, created_at) VALUES (?,?,?,?)",
                         (f"{i['project']}-{i['number']}", a, b, c))
    for s, t, a, su, d in ds["events"]:
        conn.execute("INSERT INTO events VALUES (?,?,?,?,?)", (s, t, a, su, json.dumps(d, sort_keys=True)))
    conn.execute("COMMIT")
    return conn


def main():
    for name, ds in DATASETS.items():
        os.makedirs(ds["out"], exist_ok=True)
        doc = json_v1(ds)
        for v in range(1, 5):
            with open(os.path.join(ds["out"], f"{ds['prefix']}v{v}.json"), "w") as fh:
                json.dump(doc, fh, indent=2)
                fh.write("\n")
            if v < 4:
                doc = JM.MIGRATIONS[v](doc)
        for v in range(1, 5):
            path = os.path.join(ds["out"], f"{ds['prefix']}v{v}.db")
            conn = sqlite_v1(path, ds)
            conn.execute("BEGIN")
            for step in range(1, v):
                SM.MIGRATIONS[step](conn)
                conn.execute(f"PRAGMA user_version = {step + 1}")
            conn.execute("COMMIT")
            conn.execute("VACUUM")
            conn.close()
        print(name, "ok", sorted(os.listdir(ds["out"])))


main()
