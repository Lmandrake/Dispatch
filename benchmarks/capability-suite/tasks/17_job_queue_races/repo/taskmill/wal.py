"""The write-ahead log (format and rules: docs/WAL.md).

Records are JSON objects with an int ``seq`` and an ``op``, framed as
``magic | u32 length | u32 crc32 | payload`` in numbered segment files.
"""

import os
import re
import struct
import threading
import zlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import codec
from .errors import WalCorrupt, WalError

MAGIC = b"TMW1"
HEADER = struct.Struct(">4sII")
SEGMENT_RE = re.compile(r"^wal-(\d{6})\.log$")
BATCH_SYNC_BYTES = 64 * 1024


def segment_name(n: int) -> str:
    return f"wal-{n:06d}.log"


def encode_record(record: dict) -> bytes:
    """The on-disk bytes for one record."""
    if not isinstance(record, dict) or not isinstance(record.get("seq"), int) or "op" not in record:
        raise WalError("a WAL record needs an int 'seq' and an 'op'")
    payload = codec.encode(record)
    return HEADER.pack(MAGIC, len(payload), zlib.crc32(payload)) + payload


@dataclass
class SegmentInfo:
    path: str
    number: int
    size: int
    records: int = 0
    min_seq: Optional[int] = None
    max_seq: Optional[int] = None
    good_bytes: int = 0


@dataclass
class TornTail:
    path: str
    offset: int        # where the bad record starts (= bytes kept)
    size: int          # file size before repair
    reason: str

    def to_dict(self) -> dict:
        return {"path": os.path.basename(self.path), "offset": self.offset, "size": self.size,
                "reason": self.reason}


@dataclass
class ScanResult:
    records: List[dict] = field(default_factory=list)
    segments: List[SegmentInfo] = field(default_factory=list)
    torn: Optional[TornTail] = None

    @property
    def max_seq(self) -> int:
        return max((r["seq"] for r in self.records), default=0)


def list_segments(directory: str) -> List[SegmentInfo]:
    out = []
    try:
        names = os.listdir(directory)
    except FileNotFoundError:
        return out
    for name in names:
        m = SEGMENT_RE.match(name)
        if m:
            path = os.path.join(directory, name)
            out.append(SegmentInfo(path, int(m.group(1)), os.path.getsize(path)))
    out.sort(key=lambda s: s.number)
    return out


def read_segment(path: str):
    """Parse one segment: ``(records, good_bytes, problem)``.

    ``problem`` is None for a clean segment, else ``(offset, reason, at_eof)``
    describing the first bad record; ``at_eof`` is true when the bad record
    runs to (or past) the end of the file, i.e. it could be a torn write.
    """
    with open(path, "rb") as fh:
        data = fh.read()
    records = []
    pos = 0
    n = len(data)
    while pos < n:
        if n - pos < HEADER.size:
            return records, pos, (pos, "short header", True)
        magic, length, crc = HEADER.unpack_from(data, pos)
        if magic != MAGIC:
            return records, pos, (pos, "bad magic", False)
        start = pos + HEADER.size
        end = start + length
        if end > n:
            return records, pos, (pos, "short payload", True)
        payload = data[start:end]
        if zlib.crc32(payload) != crc:
            return records, pos, (pos, "bad crc", end == n)
        try:
            rec = codec.loads(payload)
        except (UnicodeDecodeError, ValueError):
            return records, pos, (pos, "bad json", end == n)
        if not isinstance(rec, dict) or not isinstance(rec.get("seq"), int):
            return records, pos, (pos, "not a record", end == n)
        records.append(rec)
        pos = end
    return records, pos, None


def scan(directory: str) -> ScanResult:
    """Read every segment. Torn tail of the newest segment is reported, not raised."""
    result = ScanResult(segments=list_segments(directory))
    for i, seg in enumerate(result.segments):
        records, good, problem = read_segment(seg.path)
        seg.records = len(records)
        seg.good_bytes = good
        if records:
            seqs = [r["seq"] for r in records]
            seg.min_seq, seg.max_seq = min(seqs), max(seqs)
        result.records.extend(records)
        if problem is not None:
            offset, reason, at_eof = problem
            newest = i == len(result.segments) - 1
            if not (newest and at_eof):
                raise WalCorrupt(f"{os.path.basename(seg.path)}: {reason} at byte {offset}")
            result.torn = TornTail(seg.path, offset, seg.size, reason)
    return result


class WriteAheadLog:
    def __init__(self, directory: str, fsync: str = "always", segment_bytes: int = 1 << 20, hooks=None):
        self.directory = directory
        self.fsync = fsync
        self.segment_bytes = segment_bytes
        self.hooks = hooks
        self._lock = threading.Lock()
        self._fh = None
        self._current: Optional[SegmentInfo] = None
        self._segments: Dict[int, SegmentInfo] = {}
        self._unsynced = 0
        self._closed = False
        self.records_written = 0
        self.bytes_written = 0
        self.rotations = 0

    # ------------------------------------------------------------ lifecycle

    def open(self) -> ScanResult:
        """Scan the existing log and get ready to append. Returns what was found."""
        os.makedirs(self.directory, exist_ok=True)
        result = scan(self.directory)
        with self._lock:
            self._segments = {s.number: s for s in result.segments}
            if result.segments:
                newest = result.segments[-1]
                self._current = newest
                self._fh = open(newest.path, "ab")
                newest.size = self._fh.tell()
            else:
                self._start_segment_locked(1)
        return result

    def _start_segment_locked(self, number: int) -> None:
        if self._fh is not None:
            self._sync_locked(force=True)
            self._fh.close()
        path = os.path.join(self.directory, segment_name(number))
        self._fh = open(path, "ab")
        self._current = SegmentInfo(path, number, self._fh.tell())
        self._segments[number] = self._current
        _fsync_dir(self.directory)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._fh is not None:
                self._sync_locked(force=True)
                self._fh.close()
                self._fh = None

    @property
    def closed(self) -> bool:
        return self._closed

    # --------------------------------------------------------------- append

    def append(self, records: List[dict]) -> None:
        """Write ``records`` (in the given order) durably per the fsync policy."""
        if not records:
            return
        if self.hooks is not None:
            for rec in records:
                self.hooks.fire("wal.append", record=rec)
        blobs = [encode_record(r) for r in records]
        with self._lock:
            if self._closed:
                raise WalError("write-ahead log is closed")
            for rec, blob in zip(records, blobs):
                if self._current.size >= self.segment_bytes and self._current.records:
                    self._start_segment_locked(self._current.number + 1)
                    self.rotations += 1
                self._fh.write(blob)
                seg = self._current
                seg.size += len(blob)
                seg.records += 1
                seq = rec["seq"]
                seg.min_seq = seq if seg.min_seq is None else min(seg.min_seq, seq)
                seg.max_seq = seq if seg.max_seq is None else max(seg.max_seq, seq)
                self._unsynced += len(blob)
                self.records_written += 1
                self.bytes_written += len(blob)
            self._fh.flush()
            self._sync_locked(force=False)

    def _sync_locked(self, force: bool) -> None:
        if self._fh is None:
            return
        if self.fsync == "never" and not force:
            return
        if self.fsync == "batch" and not force and self._unsynced < BATCH_SYNC_BYTES:
            return
        self._fh.flush()
        if self.fsync != "never":
            os.fsync(self._fh.fileno())
        self._unsynced = 0

    def sync(self) -> None:
        with self._lock:
            self._sync_locked(force=True)

    # ------------------------------------------------------------ segments

    def rotate(self) -> int:
        """Start a new segment now (used by checkpoints). Returns its number."""
        with self._lock:
            if self._closed:
                raise WalError("write-ahead log is closed")
            if self._current.records == 0 and self._current.size == 0:
                return self._current.number
            self._start_segment_locked(self._current.number + 1)
            self.rotations += 1
            return self._current.number

    def drop_through(self, seq: int) -> List[str]:
        """Delete non-current segments whose records all have ``seq <= seq``."""
        removed = []
        with self._lock:
            for number in sorted(self._segments):
                seg = self._segments[number]
                if seg is self._current:
                    continue
                if seg.max_seq is None or seg.max_seq <= seq:
                    try:
                        os.remove(seg.path)
                    except FileNotFoundError:
                        pass
                    removed.append(os.path.basename(seg.path))
                    del self._segments[number]
        if removed:
            _fsync_dir(self.directory)
        return removed

    def segments(self) -> List[SegmentInfo]:
        with self._lock:
            return [self._segments[n] for n in sorted(self._segments)]

    def current_segment(self) -> Optional[str]:
        with self._lock:
            return None if self._current is None else self._current.path


def _fsync_dir(directory: str) -> None:
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def verify(directory: str) -> dict:
    """A read-only health report for ``taskmill wal verify``."""
    try:
        result = scan(directory)
    except WalCorrupt as exc:
        return {"ok": False, "error": str(exc)}
    seqs = [r["seq"] for r in result.records]
    in_order = all(a < b for a, b in zip(seqs, seqs[1:]))
    return {
        "ok": True,
        "segments": len(result.segments),
        "records": len(result.records),
        "min_seq": min(seqs, default=None),
        "max_seq": max(seqs, default=None),
        "duplicate_seqs": len(seqs) - len(set(seqs)),
        "file_order_is_seq_order": in_order,
        "torn_tail": result.torn.to_dict() if result.torn else None,
    }
