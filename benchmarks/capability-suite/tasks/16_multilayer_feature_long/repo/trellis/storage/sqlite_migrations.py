"""SQLite schema: the current DDL and the upgrade chain for older databases.

The schema version lives in ``PRAGMA user_version``.  A brand-new database
is created directly from ``CURRENT_SCHEMA`` and stamped with
``SCHEMA_VERSION``; an existing database with a lower version is upgraded
one step at a time by the functions in ``MIGRATIONS``.  A database whose
version is higher than ``SCHEMA_VERSION`` is refused.

Both paths must end in the same schema.  ``tests/test_storage.py`` checks
that a database upgraded from version 1 has exactly the tables and columns
(names, order, declared types, defaults) of a fresh one, so when the schema
changes, change ``CURRENT_SCHEMA`` *and* add a migration.

Schema history (mirrors the JSON format history in ``json_migrations``)
------------------------------------------------------------------------
version 1
    ``members`` table with roles reader/writer/owner; ``issues.tags`` held a
    comma-separated string and ``issues.deadline`` the due date; comments
    used ``issue_key`` and an AUTOINCREMENT id; events had no actor; no
    ``meta`` table.
version 2
    ``members`` -> ``memberships`` with roles viewer/member/admin; tags moved
    to ``issue_labels``; new ``issue_watchers``; comments rebuilt with
    ``issue``; ``meta`` table holding ``next_comment_id``.
version 3
    ``issues.deadline`` renamed ``due``; ``issues.estimate`` added; events
    gained ``actor`` (``'system'`` for old rows).
version 4 (current)
    ``projects.archived`` and ``projects.lead``; ``users.active``.

Each migration runs inside the upgrade transaction opened by
``upgrade()``; do not use ``executescript`` in a step (it commits).
"""

from trellis.errors import StorageError

SCHEMA_VERSION = 4

CURRENT_SCHEMA = [
    """CREATE TABLE meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )""",
    """CREATE TABLE users (
        username TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        email TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT '',
        active INTEGER NOT NULL DEFAULT 1
    )""",
    """CREATE TABLE projects (
        key TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        next_number INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT '',
        archived INTEGER NOT NULL DEFAULT 0,
        lead TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE issues (
        project TEXT NOT NULL,
        number INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        type TEXT NOT NULL DEFAULT 'task',
        status TEXT NOT NULL DEFAULT 'open',
        priority TEXT NOT NULL DEFAULT 'normal',
        reporter TEXT NOT NULL DEFAULT '',
        assignee TEXT NOT NULL DEFAULT '',
        due TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT '',
        closed_at TEXT NOT NULL DEFAULT '',
        estimate INTEGER,
        PRIMARY KEY (project, number)
    )""",
    """CREATE TABLE events (
        seq INTEGER PRIMARY KEY,
        timestamp TEXT NOT NULL,
        action TEXT NOT NULL,
        subject TEXT NOT NULL,
        details TEXT NOT NULL DEFAULT '{}',
        actor TEXT NOT NULL DEFAULT 'system'
    )""",
    """CREATE TABLE memberships (
        project TEXT NOT NULL,
        username TEXT NOT NULL,
        role TEXT NOT NULL,
        PRIMARY KEY (project, username)
    )""",
    """CREATE TABLE issue_labels (
        project TEXT NOT NULL,
        number INTEGER NOT NULL,
        label TEXT NOT NULL,
        PRIMARY KEY (project, number, label)
    )""",
    """CREATE TABLE issue_watchers (
        project TEXT NOT NULL,
        number INTEGER NOT NULL,
        username TEXT NOT NULL,
        PRIMARY KEY (project, number, username)
    )""",
    """CREATE TABLE comments (
        id INTEGER PRIMARY KEY,
        issue TEXT NOT NULL,
        author TEXT NOT NULL DEFAULT '',
        body TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT ''
    )""",
    "INSERT INTO meta (key, value) VALUES ('next_comment_id', '1')",
]

# The version 1 schema, kept so tests (and the fixture generator) can build
# an old database the way trellis 0.5 did.
V1_SCHEMA = [
    """CREATE TABLE users (
        username TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        email TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE projects (
        key TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        next_number INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE members (
        project TEXT NOT NULL,
        username TEXT NOT NULL,
        role TEXT NOT NULL,
        PRIMARY KEY (project, username)
    )""",
    """CREATE TABLE issues (
        project TEXT NOT NULL,
        number INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        type TEXT NOT NULL DEFAULT 'task',
        status TEXT NOT NULL DEFAULT 'open',
        priority TEXT NOT NULL DEFAULT 'normal',
        reporter TEXT NOT NULL DEFAULT '',
        assignee TEXT NOT NULL DEFAULT '',
        tags TEXT NOT NULL DEFAULT '',
        deadline TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT '',
        closed_at TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (project, number)
    )""",
    """CREATE TABLE comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        issue_key TEXT NOT NULL,
        author TEXT NOT NULL DEFAULT '',
        body TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE events (
        seq INTEGER PRIMARY KEY,
        timestamp TEXT NOT NULL,
        action TEXT NOT NULL,
        subject TEXT NOT NULL,
        details TEXT NOT NULL DEFAULT '{}'
    )""",
]

ROLE_RENAMES = {"reader": "viewer", "writer": "member", "owner": "admin"}


def _v1_to_v2(conn):
    conn.execute("""CREATE TABLE memberships (
        project TEXT NOT NULL,
        username TEXT NOT NULL,
        role TEXT NOT NULL,
        PRIMARY KEY (project, username)
    )""")
    for project, username, role in conn.execute("SELECT project, username, role FROM members").fetchall():
        conn.execute("INSERT INTO memberships VALUES (?, ?, ?)",
                     (project, username, ROLE_RENAMES.get(role, role)))
    conn.execute("DROP TABLE members")

    conn.execute("""CREATE TABLE issue_labels (
        project TEXT NOT NULL,
        number INTEGER NOT NULL,
        label TEXT NOT NULL,
        PRIMARY KEY (project, number, label)
    )""")
    conn.execute("""CREATE TABLE issue_watchers (
        project TEXT NOT NULL,
        number INTEGER NOT NULL,
        username TEXT NOT NULL,
        PRIMARY KEY (project, number, username)
    )""")
    for project, number, tags in conn.execute("SELECT project, number, tags FROM issues").fetchall():
        for label in sorted({t.strip().lower() for t in (tags or "").split(",") if t.strip()}):
            conn.execute("INSERT INTO issue_labels VALUES (?, ?, ?)", (project, number, label))
    conn.execute("ALTER TABLE issues DROP COLUMN tags")

    conn.execute("""CREATE TABLE comments_new (
        id INTEGER PRIMARY KEY,
        issue TEXT NOT NULL,
        author TEXT NOT NULL DEFAULT '',
        body TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT ''
    )""")
    conn.execute("INSERT INTO comments_new (id, issue, author, body, created_at) "
                 "SELECT id, issue_key, author, body, created_at FROM comments")
    conn.execute("DROP TABLE comments")
    conn.execute("ALTER TABLE comments_new RENAME TO comments")
    next_id = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM comments").fetchone()[0]
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO meta VALUES ('next_comment_id', ?)", (str(next_id),))


def _v2_to_v3(conn):
    conn.execute("ALTER TABLE issues RENAME COLUMN deadline TO due")
    conn.execute("ALTER TABLE issues ADD COLUMN estimate INTEGER")
    conn.execute("ALTER TABLE events ADD COLUMN actor TEXT NOT NULL DEFAULT 'system'")


def _v3_to_v4(conn):
    conn.execute("ALTER TABLE projects ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE projects ADD COLUMN lead TEXT NOT NULL DEFAULT ''")
    conn.execute("ALTER TABLE users ADD COLUMN active INTEGER NOT NULL DEFAULT 1")


MIGRATIONS = {
    1: _v1_to_v2,
    2: _v2_to_v3,
    3: _v3_to_v4,
}


def get_version(conn):
    return conn.execute("PRAGMA user_version").fetchone()[0]


def _set_version(conn, version):
    conn.execute(f"PRAGMA user_version = {int(version)}")


def _is_empty(conn):
    return conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0] == 0


def create(conn, statements=None, version=SCHEMA_VERSION):
    """Create a schema in an empty database (current schema by default)."""
    conn.execute("BEGIN")
    try:
        for stmt in statements or CURRENT_SCHEMA:
            conn.execute(stmt)
        _set_version(conn, version)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def upgrade(conn):
    """Bring the database to SCHEMA_VERSION.  Returns the version it had
    before (0 for a brand-new database).  All steps run in one transaction:
    either the database ends at SCHEMA_VERSION or it is left untouched."""
    if _is_empty(conn):
        create(conn)
        return 0
    original = version = get_version(conn)
    if version < 1:
        raise StorageError("database has no trellis schema version (user_version 0)")
    if version > SCHEMA_VERSION:
        raise StorageError(
            f"database has schema version {version}; this trellis only "
            f"understands up to version {SCHEMA_VERSION}"
        )
    if version == SCHEMA_VERSION:
        return original
    conn.execute("BEGIN")
    try:
        while version < SCHEMA_VERSION:
            step = MIGRATIONS.get(version)
            if step is None:
                raise StorageError(f"no migration from schema version {version}")
            step(conn)
            version += 1
            _set_version(conn, version)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return original
