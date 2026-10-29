"""Independent version 3 encoder written from docs/FORMAT_v3.md, used by the hidden tests.

``encode_v3(cols, columns, metadata, chunk_rows)`` gives the exact bytes a conforming writer
produces.  ``build`` / ``Archive.to_bytes`` expose the pieces so tests can assemble damaged
files with correct (or deliberately wrong) checksums.
"""
import math
import struct
import zlib

TYPE = {"ts": 1, "int": 2, "float": 3, "str": 4, "bool": 5}
M64 = (1 << 64) - 1


def crc(b):
    return zlib.crc32(b) & 0xFFFFFFFF


def uv(n):
    assert 0 <= n <= M64
    out = b""
    while n >= 0x80:
        out += bytes([(n & 0x7F) | 0x80])
        n >>= 7
    return out + bytes([n])


def sv(n):
    return uv(((n << 1) ^ (n >> 63)) & M64)


def s64(n):
    n &= M64
    return n - (1 << 64) if n >= 1 << 63 else n


def lsb_bitmap(flags):
    b = bytearray(-(-len(flags) // 8))
    for i, f in enumerate(flags):
        if f:
            b[i // 8] |= 1 << (i % 8)
    return bytes(b)


def u16s(s):
    e = s.encode("utf-8") if isinstance(s, str) else s
    return struct.pack("<H", len(e)) + e


def fpat(v):
    return int.from_bytes(struct.pack("<d", v), "little")


def enc_plain(ty, vals):
    if ty in ("ts", "int"):
        return b"".join(struct.pack("<q", v) for v in vals)
    if ty == "float":
        return b"".join(struct.pack("<d", v) for v in vals)
    return b"".join(uv(len(v.encode())) + v.encode() for v in vals)


def enc_varint(vals):
    return b"".join(sv(v) for v in vals)


def enc_delta2(vals):
    out = b""
    for i in range(len(vals)):
        if i == 0:
            out += sv(vals[0])
        elif i == 1:
            out += sv(s64(vals[1] - vals[0]))
        else:
            out += sv(s64(s64(vals[i] - vals[i - 1]) - s64(vals[i - 1] - vals[i - 2])))
    return out


def enc_xor(vals):
    out = b""
    prev = 0
    for v in vals:
        x = fpat(v) ^ prev
        prev = fpat(v)
        if x == 0:
            out += b"\x80"
            continue
        b = x.to_bytes(8, "big")
        lz = 0
        while b[lz] == 0:
            lz += 1
        tz = 0
        while b[7 - tz] == 0:
            tz += 1
        out += bytes([(lz << 4) | tz]) + b[lz:8 - tz]
    return out


def enc_dict(vals):
    entries = list(dict.fromkeys(vals))
    pos = {v: i for i, v in enumerate(entries)}
    out = uv(len(entries))
    for e in entries:
        out += uv(len(e.encode())) + e.encode()
    return out + b"".join(uv(pos[v]) for v in vals)


CANDS = {"ts": [(1, lambda t, v: enc_plain(t, v)), (3, lambda t, v: enc_delta2(v))],
         "int": [(1, lambda t, v: enc_plain(t, v)), (2, lambda t, v: enc_varint(v))],
         "float": [(1, lambda t, v: enc_plain(t, v)), (4, lambda t, v: enc_xor(v))],
         "str": [(1, lambda t, v: enc_plain(t, v)), (5, lambda t, v: enc_dict(v))],
         "bool": [(6, lambda t, v: lsb_bitmap(v))]}


class Segment:
    def __init__(self, enc, codec, nulls, stored, raw_len, stats):
        self.enc, self.codec, self.nulls, self.stored, self.raw_len = enc, codec, nulls, stored, raw_len
        self.stats = stats          # None, or (min_bytes, max_bytes) 8 bytes each
        self.has_stats = 0 if stats is None else 1
        self.stored_len = None      # override for the footer

    def entry(self):
        sl = len(self.stored) if self.stored_len is None else self.stored_len
        out = struct.pack("<BBIII", self.enc, self.codec, self.nulls, sl, self.raw_len)
        out += bytes([self.has_stats])
        if self.stats is not None:
            out += self.stats[0] + self.stats[1]
        return out


def make_segment(ty, values):
    rows = len(values)
    nn = [v for v in values if v is not None]
    nulls = rows - len(nn)
    if rows and nulls == rows:
        return Segment(0, 0, nulls, b"", 0, None)
    best = None
    for code, fn in CANDS[ty]:
        vb = fn(ty, nn)
        if best is None or len(vb) < len(best[1]):
            best = (code, vb)
    raw = (lsb_bitmap([v is not None for v in values]) if nulls else b"") + best[1]
    z = zlib.compress(raw, 6)
    stored, codec = (z, 1) if len(z) < len(raw) else (raw, 0)
    stats = None
    if ty in ("ts", "int", "float"):
        usable = [v for v in nn if not (ty == "float" and math.isnan(v))]
        if usable:
            fmt = "<d" if ty == "float" else "<q"
            stats = (struct.pack(fmt, min(usable)), struct.pack(fmt, max(usable)))
    return Segment(best[0], codec, nulls, stored, len(raw), stats)


def raw_segment(raw, enc, nulls=0, stats=None, codec=0, stored=None, raw_len=None):
    """A hand-made segment (codec none unless ``codec``/``stored`` given)."""
    s = Segment(enc, codec, nulls, raw if stored is None else stored,
                len(raw) if raw_len is None else raw_len, stats)
    return s


def stats_i64(lo, hi):
    return (struct.pack("<q", lo), struct.pack("<q", hi))


class Chunk:
    def __init__(self, rows, segments):
        self.rows = rows
        self.segments = segments
        self.offset = None        # overrides
        self.length = None
        self.crc = None
        self.extra = b""          # bytes inserted after the chunk crc

    def body(self):
        return b"".join(s.stored for s in self.segments)


class Archive:
    def __init__(self, cols, metadata, chunk_rows, chunks, row_count):
        self.cols = [(TYPE[t] if isinstance(t, str) else t, 1 if nl else 0,
                      n.encode() if isinstance(n, str) else n) for n, t, nl in cols]
        self.meta = [(k, v) for k, v in metadata.items()]
        self.flags = 0
        self.chunk_rows = chunk_rows
        self.chunks = chunks
        self.row_count = row_count
        self.header_crc = None
        self.footer_crc = None
        self.footer_extra = b""
        self.footer_offset = None
        self.footer_length = None
        self.end_magic = b"TSR3"
        self.chunk_count = None

    def header(self):
        h = b"TSAR" + struct.pack("<HHIHH", 3, self.flags, self.chunk_rows, len(self.cols),
                                  len(self.meta))
        for code, fl, name in self.cols:
            h += struct.pack("<BBB", code, fl, len(name)) + name
        for k, v in self.meta:
            h += u16s(k) + u16s(v)
        return h + struct.pack("<I", crc(h) if self.header_crc is None else self.header_crc)

    def to_bytes(self):
        out = self.header()
        entries = b""
        for ch in self.chunks:
            body = ch.body()
            off = len(out) if ch.offset is None else ch.offset
            ln = len(body) if ch.length is None else ch.length
            entries += struct.pack("<QII", off, ln, ch.rows) + b"".join(s.entry() for s in ch.segments)
            out += body + struct.pack("<I", crc(body) if ch.crc is None else ch.crc) + ch.extra
        n = len(self.chunks) if self.chunk_count is None else self.chunk_count
        footer = struct.pack("<QI", self.row_count, n) + entries + self.footer_extra
        off = len(out) if self.footer_offset is None else self.footer_offset
        fl = len(footer) if self.footer_length is None else self.footer_length
        fc = crc(footer) if self.footer_crc is None else self.footer_crc
        return out + footer + struct.pack("<QII", off, fl, fc) + self.end_magic


def build(cols, columns, metadata=None, chunk_rows=1024):
    """cols: [(name, type, nullable)], columns: one list of values per column."""
    metadata = metadata or {}
    n = len(columns[0]) if columns else 0
    chunks = []
    for start in range(0, n, chunk_rows):
        stop = min(n, start + chunk_rows)
        segs = [make_segment(t, col[start:stop]) for (name, t, nl), col in zip(cols, columns)]
        chunks.append(Chunk(stop - start, segs))
    return Archive(cols, metadata, chunk_rows, chunks, n)


def encode_v3(cols, columns, metadata=None, chunk_rows=1024):
    return build(cols, columns, metadata, chunk_rows).to_bytes()


# ---- independent v1 / v2 encoders (docs/FORMAT_v1.md, docs/FORMAT_v2.md) ----------------------

def encode_v1(cols, columns):
    rows = list(zip(*columns)) if columns and columns[0] else []
    b = b"TSAR" + struct.pack("<HHHI", 1, 0, len(cols), len(rows))
    for name, ty, _ in cols:
        b += struct.pack("<BB", TYPE[ty], len(name)) + name.encode()
    for r in rows:
        for (name, ty, _), v in zip(cols, r):
            if ty == "float":
                b += struct.pack("<d", v)
            elif ty == "str":
                e = v.encode("latin-1")
                b += struct.pack("<H", len(e)) + e
            else:
                b += struct.pack("<q", v)
    return b + struct.pack("<I", crc(b))


def encode_v2(cols, columns, meta):
    n = len(columns[0])
    h = b"TSAR" + struct.pack("<HHIHH", 2, 0, n, len(cols), len(meta))
    for k, v in meta.items():
        h += u16s(k) + u16s(v)
    out = h + struct.pack("<I", crc(h))
    for (name, ty, _), vals in zip(cols, columns):
        if ty in ("ts", "int"):
            d = b"".join(struct.pack("<q", v) for v in vals)
        elif ty == "float":
            d = b"".join(struct.pack("<d", v) for v in vals)
        elif ty == "str":
            blobs = [v.encode() for v in vals]
            ends, e = [], 0
            for x in blobs:
                e += len(x)
                ends.append(struct.pack("<I", e))
            d = b"".join(ends) + b"".join(blobs)
        else:
            bm = bytearray((len(vals) + 7) // 8)
            for i, v in enumerate(vals):
                if v:
                    bm[i >> 3] |= 0x80 >> (i & 7)
            d = bytes(bm)
        out += struct.pack("<BB", TYPE[ty], len(name)) + name.encode() + struct.pack("<I", len(d)) \
            + d + struct.pack("<I", crc(d))
    return out + b"RAST"
