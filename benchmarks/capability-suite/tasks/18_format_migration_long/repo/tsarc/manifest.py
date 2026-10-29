"""Directory manifests: a JSON file recording the archives in a directory with their
SHA-256, size, format version, row count and time range, so a copy can be checked later.

``write_manifest(dir)`` writes ``MANIFEST.json``; ``check_manifest(dir)`` compares the
directory against it and returns a list of problem lines (empty when everything matches).
"""
import hashlib
import json
from pathlib import Path

from .errors import TsarcError

NAME = "MANIFEST.json"
SCHEMA_VERSION = 1


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def build_manifest(directory, pattern="*.tsa"):
    from .archive import ArchiveReader

    directory = Path(directory)
    files = []
    for p in sorted(directory.glob(pattern)):
        if not p.is_file():
            continue
        entry = {"name": p.name, "size": p.stat().st_size, "sha256": _sha256(p)}
        try:
            rd = ArchiveReader(p)
        except (TsarcError, OSError) as exc:
            entry["error"] = str(exc)
        else:
            rng = rd.time_range()
            entry.update(version=rd.version, rows=rd.num_rows, schema=rd.schema.to_text(),
                         first=rng[0] if rng else None, last=rng[1] if rng else None)
        files.append(entry)
    return {"manifest_version": SCHEMA_VERSION, "files": files}


def write_manifest(directory, pattern="*.tsa"):
    from .fileutil import atomic_write_bytes

    m = build_manifest(directory, pattern)
    text = json.dumps(m, indent=2, ensure_ascii=False) + "\n"
    atomic_write_bytes(Path(directory) / NAME, text.encode("utf-8"))
    return m


def check_manifest(directory, pattern="*.tsa"):
    directory = Path(directory)
    try:
        stored = json.loads((directory / NAME).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [f"no {NAME} in {directory}"]
    except json.JSONDecodeError as exc:
        return [f"{NAME} is not valid JSON: {exc}"]
    if stored.get("manifest_version") != SCHEMA_VERSION:
        return [f"unsupported manifest version {stored.get('manifest_version')!r}"]
    current = {e["name"]: e for e in build_manifest(directory, pattern)["files"]}
    problems = []
    seen = set()
    for e in stored.get("files", []):
        name = e["name"]
        seen.add(name)
        now = current.get(name)
        if now is None:
            problems.append(f"{name}: missing")
            continue
        if now["sha256"] != e["sha256"]:
            problems.append(f"{name}: content changed")
        elif "error" in now and "error" not in e:
            problems.append(f"{name}: no longer readable: {now['error']}")
    for name in sorted(set(current) - seen):
        problems.append(f"{name}: not in manifest")
    return problems
