# Archive format version 3 (chunked columnar) — agreed spec, not yet implemented

Version 3 splits an archive into **chunks** of rows. Inside a chunk every
column is stored as its own **segment**, encoded with a type-specific
encoding and usually zlib-compressed. A footer **index** at the end of the
file records where every chunk and segment is, plus per-segment statistics,
so a reader can open a file by reading only the header and the footer, and a
time-range query can skip every chunk that cannot contain matching rows
without decompressing it. Version 3 also adds **nullable columns** (schema
evolution: columns can be added to an existing archive, holding nulls).

Version 3 becomes the default write format. Versions 1 and 2 remain fully
supported for reading, and writing them on request must keep producing
exactly the same bytes as today.

## Conventions

* All fixed-width integers are little-endian; there is no padding or alignment.
* `crc32(x)` means `zlib.crc32(x) & 0xFFFFFFFF`.
* A **u16 string** is a u16 byte length followed by that many UTF-8 bytes (as in version 2).
* **uvarint**: an unsigned integer 0 .. 2^64-1 in LEB128 form: seven bits per byte, least
  significant group first, the high bit (0x80) set on every byte except the last. Writers
  produce the shortest form (the value 0 is the single byte `00`; 300 is `ac 02`). A reader
  rejects a uvarint that is longer than 10 bytes or whose value does not fit in 64 bits.
* **zigzag** maps a signed 64-bit integer `n` to an unsigned one:
  `(n << 1) ^ (n >> 63)` taken modulo 2^64 (0 → 0, -1 → 1, 1 → 2, -2 → 3, ...). The inverse is
  `(z >> 1) ^ -(z & 1)`. A **svarint** is the uvarint of the zigzag of a value.
* **Wrapping arithmetic**: where this document says a difference "wraps", it is computed
  modulo 2^64 and interpreted as a signed 64-bit integer (two's complement). Example: the
  wrapped difference `(2^63 - 1) - (-2^63)` is `-1`. Decoding adds the differences back with
  the same wrapping, so every sequence of i64 values round-trips exactly.
* **bitmaps** in version 3 are **least significant bit first**: entry `i` is bit `i % 8`
  (value `1 << (i % 8)`) of byte `i // 8`. A bitmap of `n` entries is `ceil(n / 8)` bytes and
  its unused high bits in the last byte are zero. (Version 2 bool columns use the opposite,
  most-significant-first order; that does not change.)

## Layout

```
header
chunk 0 .. chunk (chunk_count - 1)
footer
trailer            20 bytes
```

The first chunk starts immediately after the header, each chunk immediately follows the
previous one, and the footer immediately follows the last chunk (or the header, when there
are no chunks).

## Header

| size | type        | field          | notes                                               |
|-----:|-------------|----------------|-----------------------------------------------------|
| 4    | bytes       | magic          | `TSAR`                                              |
| 2    | u16         | version        | 3                                                   |
| 2    | u16         | flags          | must be 0                                           |
| 4    | u32         | chunk_rows     | rows per chunk used by the writer, at least 1       |
| 2    | u16         | column_count   |                                                     |
| 2    | u16         | metadata_count |                                                     |
| ...  |             | columns        | `column_count` column descriptors, schema order     |
| ...  |             | metadata       | `metadata_count` (key, value) pairs of u16 strings, in insertion order |
| 4    | u32         | header_crc     | crc32 of every header byte before this field        |

Column descriptor:

| size | type  | field  | notes                                                         |
|-----:|-------|--------|---------------------------------------------------------------|
| 1    | u8    | type   | 1 = ts, 2 = int, 3 = float, 4 = str, 5 = bool (same codes as before) |
| 1    | u8    | flags  | bit 0 = nullable; other bits must be 0                        |
| 1+n  |       | name   | u8 length, then that many ASCII bytes                         |

The row count is not in the header; it is in the footer.

## Chunks

Rows are split into chunks in order: every chunk except the last holds exactly
`chunk_rows` rows, the last holds the remainder (1 .. `chunk_rows`). An archive with no rows
has no chunks.

A chunk is its segments, one per column in schema order, concatenated with nothing between
them, followed by a u32 `chunk_crc`: the crc32 of all the segment bytes of that chunk.

| size        | field       |
|------------:|-------------|
| `length`    | segment 0 stored bytes, segment 1 stored bytes, ... (`length` is the chunk's length in the footer) |
| 4           | chunk_crc   |

### Segments

A segment holds one column's values for the rows of one chunk. It is built in three steps.

1. **Nulls.** Let `rows` be the chunk's row count and `null_count` the number of null values
   of this column in the chunk (always 0 for a column that is not nullable).
   * If `null_count == rows` (and `rows > 0`), the segment uses encoding `NULL`: its raw
     bytes are empty, and steps 2 and 3 are skipped (codec `none`, both lengths 0).
   * If `0 < null_count < rows`, the raw bytes start with a **validity bitmap** of `rows`
     entries (LSB first, see Conventions); entry `i` is 1 when row `i` of the chunk is
     not null.
   * If `null_count == 0`, there is no bitmap.
2. **Values.** The non-null values, in row order, are encoded with the segment's encoding
   (below) and appended to the raw bytes.
3. **Compression.** Let `z = zlib.compress(raw, 6)`. If `len(z) < len(raw)` the segment
   is stored as `z` with codec `zlib`; otherwise it is stored as `raw` with codec `none`.
   `raw_len` is `len(raw)` and `stored_len` is the length of what was stored.

### Encodings

| code | name    | types      | value bytes                                                         |
|-----:|---------|------------|----------------------------------------------------------------------|
| 0    | NULL    | any nullable | none (every value of the segment is null)                          |
| 1    | PLAIN   | ts, int, float, str | ts / int: i64 per value; float: f64 per value; str: uvarint byte length then the UTF-8 bytes, per value |
| 2    | VARINT  | int        | svarint per value                                                    |
| 3    | DELTA2  | ts         | see below                                                            |
| 4    | XOR     | float      | see below                                                            |
| 5    | DICT    | str        | see below                                                            |
| 6    | BITPACK | bool       | a bitmap (LSB first) with one entry per value, 1 = True              |

**DELTA2** (delta-of-delta) for values `v0, v1, ..., v(n-1)`: svarint of `v0`; if `n >= 2`,
svarint of `d1 = v1 - v0`; then for every `i >= 2`, svarint of
`(v(i) - v(i-1)) - (v(i-1) - v(i-2))`. Every subtraction wraps (see Conventions). Zero values
produce no bytes. Example: `[1000, 1010, 1020, 1031]` encodes as svarints of
`1000, 10, 0, 1`, i.e. `d0 0f 14 00 02`.

**XOR** for floats: take the 64-bit pattern of each value (`struct.pack("<d")` read as a u64)
and XOR it with the pattern of the previous value; the first value is XORed with 0. Each
XOR result `x` is written as follows. If `x == 0`, the single byte `0x80`. Otherwise let
`b` be `x` as 8 bytes **big-endian**, `lz` the number of leading `00` bytes of `b`, and `tz`
the number of trailing `00` bytes of `b`; write the control byte `(lz << 4) | tz` followed
by the bytes `b[lz : 8 - tz]` (most significant first). So `lz + tz <= 7` for every
control byte except `0x80`. A reader rejects any other control byte (where `lz + tz > 7`,
except exactly `0x80`). Example: `[1.0, 1.0, 1.5]` encodes as
`06 3f f0` (`x = 0x3ff0000000000000`), `80`, `16 08` (`x = 0x0008000000000000`).

**DICT** for strings: the dictionary is the distinct non-null values in order of first
appearance. Write the uvarint number of entries, then each entry as uvarint byte length and
UTF-8 bytes, then for every value the uvarint index of its entry.

**Choosing the encoding.** For a segment that is not `NULL`, the writer encodes the values with
every candidate encoding of the column's type and uses the one with the fewest value bytes;
on a tie, the lower code wins.

| type  | candidates      |
|-------|-----------------|
| ts    | PLAIN, DELTA2   |
| int   | PLAIN, VARINT   |
| float | PLAIN, XOR      |
| str   | PLAIN, DICT     |
| bool  | BITPACK         |

The comparison is on the value bytes only (the bitmap is the same for all candidates) and
happens before compression. A reader accepts any encoding listed for the type (and `NULL` for
a nullable column), whichever the writer would have chosen.

## Footer

| size | type | field        | notes                                  |
|-----:|------|--------------|----------------------------------------|
| 8    | u64  | row_count    | total rows in the archive              |
| 4    | u32  | chunk_count  |                                        |
| ...  |      | chunk entries | `chunk_count` entries, in chunk order |

Chunk entry:

| size | type | field   | notes                                                  |
|-----:|------|---------|--------------------------------------------------------|
| 8    | u64  | offset  | file offset of the chunk's first byte                  |
| 4    | u32  | length  | bytes of segments (not counting the 4-byte chunk_crc)  |
| 4    | u32  | rows    | rows in the chunk                                      |
| ...  |      | segment entries | one per column, schema order                   |

Segment entry:

| size | type  | field      | notes                                                         |
|-----:|-------|------------|---------------------------------------------------------------|
| 1    | u8    | encoding   | code from the encodings table                                 |
| 1    | u8    | codec      | 0 = none, 1 = zlib                                            |
| 4    | u32   | null_count |                                                               |
| 4    | u32   | stored_len | bytes of the segment in the chunk                             |
| 4    | u32   | raw_len    | bytes of the raw segment (after decompression)                |
| 1    | u8    | has_stats  | 0 or 1                                                        |
| 8    |       | min        | only when `has_stats` is 1                                    |
| 8    |       | max        | only when `has_stats` is 1                                    |

A segment's stored bytes start at the chunk's `offset` plus the `stored_len` of the segments
before it in the same chunk.

**Statistics.** `has_stats` is 1 exactly when the column type is `ts`, `int` or `float` and
the segment has at least one non-null value that is not NaN. `min` and `max` are the smallest
and largest such values, as i64 (ts, int) or f64 (float); NaN values are ignored. When
several values are equal to the minimum (or maximum), such as `0.0` and `-0.0`, the one that
comes first in row order is stored. Columns of type `str` and `bool` never have statistics.
The time column is never null, so every chunk has statistics for it: these are what range
queries use to skip chunks.

## Trailer (last 20 bytes)

| size | type  | field         | notes                              |
|-----:|-------|---------------|------------------------------------|
| 8    | u64   | footer_offset | file offset of the footer          |
| 4    | u32   | footer_length | bytes of the footer                |
| 4    | u32   | footer_crc    | crc32 of the footer bytes          |
| 4    | bytes | end_magic     | `TSR3`                             |

## Reading

Opening a version 3 archive reads and checks the header, trailer and footer only. Chunk data
is read when it is needed: loading the whole table (`ArchiveReader.table`), a column, a
query or `verify`. Whenever a chunk's data is used, its `chunk_crc` is checked first (over
the whole chunk, even if only one column is needed), then the needed segments are decoded.
Segments stored with codec `zlib` are decompressed with exactly one call of
`zlib.decompress(stored)` each, looked up on the `zlib` module at call time (tooling replaces
`zlib.decompress` to count these calls and check that skipped chunks and unneeded columns are
never decompressed). Segments with codec `none` are not passed to `zlib` at all.

### Errors

Every problem raises `FormatError`, or its subclass `ChecksumError` for a checksum mismatch.
`FormatError` (and therefore `ChecksumError`) gains two attributes, `chunk` (int or `None`)
and `column` (column name or `None`); they are `None` unless stated below, and they are
`None` for every version 1 and version 2 error. The message (`str(exc)`) is exactly the text
given below, with `<i>` a chunk number, `<name>` a column name and `<n>`/`<code>` decimal
numbers. A file with the right magic and a version other than 1, 2 or 3 raises
`UnsupportedVersionError` as before.

Checks happen in the order listed; the first failure is raised.

**Header** (`FormatError`, `chunk` and `column` None):

1. `header: truncated` — the file ends inside the header.
2. `header: checksum mismatch` (`ChecksumError`) — `header_crc` is wrong.
3. `header: unknown flags 0x<4 hex digits>` — e.g. `header: unknown flags 0x0001`.
4. `header: column <n> has unknown type code <code>` — `<n>` is the 0-based column number;
   columns are checked in order, type code first, then flags:
   `header: column <n> has unknown flags 0x<2 hex digits>`.
5. `header: chunk_rows must be at least 1`.
6. `header: bad schema: <reason>` — names that are not ASCII or not valid column names,
   duplicate names, a first column that is not `ts`, or a nullable time column. `<reason>`
   is the text of the `SchemaError` that `Schema` raises for it.
7. `header: invalid UTF-8` — a metadata key or value.

**Trailer** (`FormatError`):

1. `trailer: truncated` — fewer than 20 bytes follow the header.
2. `trailer: bad end magic`.
3. `trailer: bad footer position` — the footer would not end exactly where the trailer starts,
   or would start before the end of the header.
4. `footer: checksum mismatch` (`ChecksumError`).

**Footer** (`FormatError`). The footer is first parsed completely (checks 1 and 2: every
chunk entry and segment entry is read, with `min`/`max` present exactly when `has_stats` is 1);
only then are the entries checked (3 to 5):

1. `footer: truncated` — the footer ends inside a field.
2. `footer: unexpected bytes after the last chunk entry`.
3. For each chunk `<i>` in order:
   1. `footer: chunk <i> is not where expected` — `offset` is not the end of the header
      (chunk 0) or the end of the previous chunk's `chunk_crc`.
   2. `footer: chunk <i> has a wrong row count` — `rows` is not `chunk_rows` for a chunk
      that is not the last, or is not 1 .. `chunk_rows` for the last.
   3. Then each segment in schema order (`'<name>'` in single quotes):
      * `footer: chunk <i>, column '<name>': encoding <code> not allowed for type <type>`
        (`NULL` counts as allowed only for a nullable column)
      * `footer: chunk <i>, column '<name>': unknown codec <code>`
      * `footer: chunk <i>, column '<name>': bad null_count <n>` — more nulls than rows,
        nulls in a column that is not nullable, `NULL` encoding with `null_count != rows`,
        or another encoding with `null_count == rows`
      * `footer: chunk <i>, column '<name>': bad stats flag <n>` — `has_stats` that is not 0
        or 1, or that differs from what the Statistics rule allows for the column type
        (1 for a str or bool column, 1 for a NULL segment, or 0 for the time column)
   4. `footer: chunk <i> length does not match its segments` — `length` differs from the
      sum of its segments' `stored_len`.
4. `footer: chunks do not end at the footer` — the end of the last chunk's `chunk_crc` (the
   end of the header when there are no chunks) is not `footer_offset`.
5. `footer: row counts do not add up to row_count`.

**Chunk data**, checked when a chunk is used:

* `chunk <i>: checksum mismatch` (`ChecksumError`, `chunk` = i, `column` None).
* Decoding a segment: `chunk` = i, `column` = the column name, and the message is
  `chunk <i>, column '<name>': ` followed by one of the reasons below. A segment is decoded in
  this order, and the first failure is reported: decompression, raw length, validity bitmap
  (its padding bits, then its count against `null_count`), the values in order, leftover
  bytes, statistics.
  * `decompression failed` — `zlib.decompress` raised.
  * `raw length mismatch` — the raw bytes (decompressed, or as stored for codec none) are
    not `raw_len` long.
  * `truncated data` — the raw bytes end inside the validity bitmap or a value.
  * `non-zero padding bits` — in the validity bitmap or a BITPACK bitmap.
  * `validity bitmap does not match null_count`.
  * `varint too long` — a uvarint longer than 10 bytes, or whose value does not fit in 64 bits.
  * `bad XOR control byte 0x<2 hex digits>`.
  * `dictionary index out of range`.
  * `invalid UTF-8`.
  * `unexpected bytes after the last value`.
  * `statistics do not match the data` — after decoding, the segment's `has_stats`, `min`
    or `max` differ from what the Statistics rule gives for the decoded values (floats are
    compared by bit pattern).

## API changes that come with version 3

These apply whatever version a file was read from.

* **Nullable columns.** `Column(name, type, nullable=False)`. Its text form is `name:type?`
  when nullable (`Column.parse` and `Schema.parse` accept the `?`). The time column cannot
  be nullable (`SchemaError: the time column cannot be nullable`). In a `Table`, `None` is
  the null value; it is accepted only in nullable columns (anything else still raises
  `SchemaError`). Table equality treats `None` as equal to `None` only. `Schema.describe()`
  shows the type of a nullable column with the `?` (`float?`).
* `write_archive(path, table, metadata=None, version=None, chunk_rows=None)`: `version`
  defaults to 3; `chunk_rows` defaults to 1024, is ignored for versions 1 and 2, and must be
  an int of at least 1 when given (else `ValueError`, whatever the version). Writing still
  replaces the file atomically. `ArchiveWriter` takes the same `chunk_rows` keyword.
* Versions 1 and 2 cannot store nullable columns: writing a schema with a nullable column
  raises `NotRepresentableError` with `column` = the first nullable column's name and `row`
  None, before any other check of that version.
* `ArchiveReader` gains `chunk_rows` and `chunk_count` (`None` for versions 1 and 2) and
  `chunks`: for version 3 a list of `ChunkInfo`, one per chunk, built from the footer
  alone; `None` for versions 1 and 2. `ChunkInfo` has `index`, `offset`, `length`, `rows`,
  `first_row` (file-wide 0-based index of the chunk's first row) and `segments`, a dict
  from column name (schema order) to `SegmentInfo` with `encoding` (the lower-case name:
  `"null"`, `"plain"`, `"varint"`, `"delta2"`, `"xor"`, `"dict"`, `"bitpack"`), `codec`
  (`"none"` or `"zlib"`), `null_count`, `stored_len`, `raw_len`, `min` and `max` (`None` when
  the segment has no statistics). Both classes are importable from `tsarc`.
* `ArchiveReader.time_range()` for version 3 comes from the footer statistics without
  reading any chunk. `num_rows`, `schema`, `metadata` likewise.
* `ArchiveReader.query(start, end, columns, where)` for version 3 reads only the chunks whose
  time statistics overlap `[start, end)` (a chunk with `max < start` or `min >= end` is
  skipped), and decodes only the segments of the columns it needs: the time column, the
  requested `columns` (all columns when `None`) and the columns named in `where` (all
  columns when `where` is a callable).
  `ArchiveReader.column(name)` decodes only that column's segments (every chunk).
  The result is the same as filtering the whole table.
* `tsarc.migrate(src, dst, chunk_rows=1024)` reads any archive and writes it to `dst` as
  version 3 with the same schema, metadata and rows; returns the number of rows.
* `tsarc.add_column(path, spec)` adds a column to a version 3 archive in place. `spec` is
  column text (`"hum:float?"`) or a `Column`; it must be nullable (else `SchemaError: a new
  column must be nullable`) and its name must be new (`SchemaError`). The column is appended
  at the end of the schema with every value null; rows, metadata and `chunk_rows` are kept.
  On a version 1 or 2 archive it raises `NotRepresentableError` (column = the new name) and
  leaves the file unchanged. Returns the new `Schema`.
* `append_rows`, `set_metadata` and `convert` keep `chunk_rows` when the result is version 3
  (`convert` to version 3 from version 1 or 2 uses 1024).
* **CSV**: the header cell of a nullable column is `name:type?`. On export a null is an
  empty field. On import, in a nullable column an empty field (after the CSV quoting is
  removed, so `""` too) is null; nullability is never inferred, it comes from the header or
  the schema. **JSON Lines**: a null is JSON `null`.
* **Stats** (`tsarc.stats`): `ColumnStats` gains `nulls` (int). `count` counts non-null
  values, and `min`/`max`/`mean`/`distinct`/`true`/`nan` ignore nulls. In the `stats` table
  the notes cell gets `nulls=<n>` at the end (space-separated after any other note) when
  `nulls > 0`.
* **Expressions**: a column value that is null makes any arithmetic or function call using
  it null, and any comparison, `in`, `between` or `~` using it false. Wherever a boolean is
  needed (an operand of `and`, `or`, `not`, or the whole filter) a null counts as false, so
  with `x` null, `x > 1` and `x <= 1` are both false and `not (x > 1)` is true.
* **Resample**: aggregates ignore nulls (`count` counts non-null values); an output column
  computed from a nullable column is nullable (except `count`), and a bucket with no
  non-null value gives null.
* **Verify**: a version 3 archive is checked completely (every chunk and segment). The ok
  line becomes `<path>: ok (v3, <rows> rows, <chunks> chunks)`; versions 1 and 2 keep
  `<path>: ok (v<version>, <rows> rows)`. Failures still print `<path>: CORRUPT: <message>`.
* **CLI**:
  * `--format-version` accepts 1, 2 or 3 and defaults to 3 everywhere it exists.
  * `import` and `convert` gain `--chunk-rows N`.
  * new `migrate SRC DST [--chunk-rows N]`: prints `migrated <n> rows to <DST> (<k> chunks)`.
  * new `add-column FILE SPEC`: prints `added column <spec text> to <FILE>` (spec text as
    `Column.to_text()` gives it).
  * `info` for a version 3 archive prints `chunks: <k> (chunk_rows <r>)` right after the
    `rows:` line, and after the metadata lines an `encodings:` block: one line per column,
    `  <name>  <encodings>` with names padded like the column lines, where `<encodings>`
    is the distinct encoding names that column's segments use, in order of first use,
    joined by `, ` (`-` for every column when the archive has no chunks). `info` reads no
    chunk data. Example:

```
file: obs.tsa
version: 3
size: 2310 bytes (2.3 KiB)
rows: 2500
chunks: 3 (chunk_rows 1024)
columns: 3
  ts    ts
  temp  float
  hum   float?
range: 2026-03-01T00:00:00Z .. 2026-03-01T00:41:39Z
metadata:
  source = lab
encodings:
  ts    delta2
  temp  xor, plain
  hum   null
```
