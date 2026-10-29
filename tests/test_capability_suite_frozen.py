"""The capability suite is frozen: every file must match MANIFEST.sha256 (see its README)."""
import hashlib
from pathlib import Path

SUITE = Path(__file__).resolve().parent.parent / "benchmarks" / "capability-suite"
PINNED = ("tasks", "ref-solutions", "generators", "verify.sh")


def _present():
    """The pinned tops this checkout holds. A public clone ships without `ref-solutions/`
    (kept private so agents under test cannot read them); its manifest then pins the rest."""
    return [top for top in PINNED if (SUITE / top).exists()]


def _manifest():
    out = {}
    tops = _present()
    for line in (SUITE / "MANIFEST.sha256").read_text().splitlines():
        digest, path = line.split(None, 1)
        if path.split("/", 1)[0] in tops:
            out[path] = digest
    return out


def _on_disk():
    files = []
    for top in _present():
        p = SUITE / top
        files += [p] if p.is_file() else [f for f in p.rglob("*") if f.is_file()
                                         and "__pycache__" not in f.parts and ".pytest_cache" not in f.parts]
    return {str(f.relative_to(SUITE)): hashlib.sha256(f.read_bytes()).hexdigest() for f in files}


def test_no_files_added_or_removed():
    assert set(_on_disk()) == set(_manifest())


def test_every_file_unchanged():
    disk, pinned = _on_disk(), _manifest()
    changed = sorted(p for p in pinned if disk.get(p) != pinned[p])
    assert not changed, "frozen capability-suite files changed: %s" % changed[:10]


def test_the_manifest_pins_every_present_top_level():
    """Filtering by presence must not let a whole shipped directory go unpinned."""
    pinned_tops = {p.split("/", 1)[0] for p in _manifest()}
    assert pinned_tops == set(_present()), (pinned_tops, _present())

