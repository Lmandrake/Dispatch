"""Upgrade chain for the JSON data-file format.

Each step takes a document of version N and returns a *new* document of
version N + 1; the input is never modified.  ``migrate`` applies the steps
one at a time, so a version 1 file passes through every step.

Format history (see also docs/STORAGE.md)
-----------------------------------------
version 1
    No ``format`` key.  Issues carried ``tags`` as one comma-separated
    string and a ``deadline`` date; there were no watchers.  Comments were
    embedded in their issue as ``"comments": [{author, body, created_at}]``
    with no ids.  Roles were ``reader`` / ``writer`` / ``owner``.  Events
    had no ``actor``.
version 2
    ``"format": "trellis"`` added.  ``tags`` became the sorted list
    ``labels``; issues gained ``watchers`` (empty).  Comments moved to a
    top-level ``comments`` list, numbered from 1 in (issue, position) order,
    with ``next_comment_id``.  Roles renamed reader->viewer, writer->member,
    owner->admin.
version 3
    Issue ``deadline`` renamed ``due``; issues gained ``estimate`` (null).
    Events gained ``actor`` (``"system"`` for migrated events).
version 4 (current)
    Projects gained ``archived`` (false) and ``lead`` (""); users gained
    ``active`` (true).
"""

import copy

from trellis.errors import StorageError

FORMAT_NAME = "trellis"
FORMAT_VERSION = 4

ROLE_RENAMES = {"reader": "viewer", "writer": "member", "owner": "admin"}


def _split_tags(text):
    if isinstance(text, list):
        parts = text
    else:
        parts = (text or "").split(",")
    return sorted({p.strip().lower() for p in parts if p.strip()})


def _v1_to_v2(doc):
    doc = copy.deepcopy(doc)
    comments = []
    issues = sorted(doc.get("issues", []), key=lambda d: (d["project"], int(d["number"])))
    for issue in issues:
        issue["labels"] = _split_tags(issue.pop("tags", ""))
        issue.setdefault("watchers", [])
        key = f"{issue['project']}-{issue['number']}"
        for c in issue.pop("comments", []) or []:
            comments.append({
                "id": len(comments) + 1,
                "issue": key,
                "author": c.get("author", ""),
                "body": c.get("body", ""),
                "created_at": c.get("created_at", ""),
            })
    doc["issues"] = issues
    doc["comments"] = comments
    doc["next_comment_id"] = len(comments) + 1
    for m in doc.get("memberships", []):
        m["role"] = ROLE_RENAMES.get(m.get("role"), m.get("role"))
    doc["format"] = FORMAT_NAME
    doc["version"] = 2
    return doc


def _v2_to_v3(doc):
    doc = copy.deepcopy(doc)
    for issue in doc.get("issues", []):
        issue["due"] = issue.pop("deadline", "") or ""
        issue.setdefault("estimate", None)
    for ev in doc.get("events", []):
        ev.setdefault("actor", "system")
    doc["version"] = 3
    return doc


def _v3_to_v4(doc):
    doc = copy.deepcopy(doc)
    for p in doc.get("projects", []):
        p.setdefault("archived", False)
        p.setdefault("lead", "")
    for u in doc.get("users", []):
        u.setdefault("active", True)
    doc["version"] = 4
    return doc


MIGRATIONS = {
    1: _v1_to_v2,
    2: _v2_to_v3,
    3: _v3_to_v4,
}


def detect_version(doc):
    if not isinstance(doc, dict):
        raise StorageError("top level of a trellis file must be an object")
    if "format" in doc and doc["format"] != FORMAT_NAME:
        raise StorageError(f"not a trellis file (format {doc['format']!r})")
    version = doc.get("version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise StorageError(f"bad format version: {version!r}")
    return version


def migrate(doc):
    """Return ``(upgraded_doc, original_version)``."""
    original = version = detect_version(doc)
    if version > FORMAT_VERSION:
        raise StorageError(
            f"data file has format version {version}; this trellis only "
            f"understands up to version {FORMAT_VERSION}"
        )
    while version < FORMAT_VERSION:
        step = MIGRATIONS.get(version)
        if step is None:
            raise StorageError(f"no migration from format version {version}")
        doc = step(doc)
        if doc.get("version") != version + 1:
            raise StorageError(f"migration from version {version} did not produce {version + 1}")
        version = doc["version"]
    return doc, original
