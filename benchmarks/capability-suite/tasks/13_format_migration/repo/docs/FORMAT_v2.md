# SLOG format version 2 (agreed spec, not yet implemented)

Version 2 fixes the limits of version 1: labels and station names become
variable-length UTF-8, timestamps get microsecond resolution, records gain a
quality score, the single whole-file checksum is replaced by per-block CRCs,
and an index footer lets tools find blocks without scanning.

Everything is little-endian. Fields are packed with no padding or alignment.
"crc32" always means `zlib.crc32(data) & 0xFFFFFFFF`. "utf-8 string" means the
string's UTF-8 encoding, at most 65535 bytes, preceded by its length in bytes
as a u16; there is no terminator, and NUL characters are allowed.

## Layout

```
header
block 0 .. block (block_count - 1)
index        block_count x 32 bytes
trailer      20 bytes
```

## Header

| offset   | size | type        | field        | notes                                       |
|---------:|-----:|-------------|--------------|---------------------------------------------|
| 0        | 4    | bytes       | magic        | `SLOG`                                      |
| 4        | 2    | u16         | version      | 2                                           |
| 6        | 2    | u16         | flags        | must be 0                                   |
| 8        | 8    | i64         | created      | Unix epoch microseconds                     |
| 16       | 4    | u32         | record_count | total records in the file                   |
| 20       | 4    | u32         | block_count  |                                             |
| 24       | 4    | u32         | block_size   | maximum records per block used by the writer|
| 28       | 2+n  | utf-8 string| station      |                                             |
| 30+n     | 4    | u32         | header_crc   | crc32 of header bytes 0 .. 30+n-1           |

## Blocks

Records are stored in file order, split into blocks. Every block except the
last holds exactly `block_size` records; the last holds the remainder
(1 .. block_size). A file with no records has no blocks. The first block
starts immediately after the header and each block immediately follows the
previous one.

| offset | size | type  | field        | notes                                         |
|-------:|-----:|-------|--------------|-----------------------------------------------|
| 0      | 4    | u32   | record_count | records in this block                         |
| 4      | 4    | u32   | payload_len  | bytes of payload                              |
| 8      | n    | bytes | payload      | the block's records, concatenated             |
| 8+n    | 4    | u32   | block_crc    | crc32 of block bytes 0 .. 8+n-1 (the 8-byte block header and the payload) |

### Record (inside a payload)

| offset | size | type        | field     | notes                                          |
|-------:|-----:|-------------|-----------|------------------------------------------------|
| 0      | 2    | u16         | sensor    |                                                |
| 2      | 1    | u8          | kind      | 0 = signed 64-bit integer, 1 = IEEE-754 double |
| 3      | 1    | u8          | flags     | bit 0 = calibrated; other bits must be 0       |
| 4      | 1    | u8          | quality   | 0 .. 100                                       |
| 5      | 8    | i64         | timestamp | Unix epoch microseconds                        |
| 13     | 8    | i64/f64     | value     | interpreted according to `kind`                |
| 21     | 2+n  | utf-8 string| label     |                                                |

## Index

One 32-byte entry per block, in block order, starting at `index_offset`
(immediately after the last block; immediately after the header when there are
no blocks).

| offset | size | type | field         | notes                                         |
|-------:|-----:|------|---------------|-----------------------------------------------|
| 0      | 8    | u64  | block_offset  | file offset of the block's first byte         |
| 8      | 4    | u32  | first_record  | file-wide 0-based index of the block's first record |
| 12     | 4    | u32  | record_count  | records in the block                          |
| 16     | 8    | i64  | min_timestamp | smallest timestamp in the block               |
| 24     | 8    | i64  | max_timestamp | largest timestamp in the block                |

## Trailer (last 20 bytes of the file)

| offset | size | type  | field        | notes                                  |
|-------:|-----:|-------|--------------|----------------------------------------|
| 0      | 8    | u64   | index_offset |                                        |
| 8      | 4    | u32   | block_count  | must equal the header's block_count    |
| 12     | 4    | u32   | index_crc    | crc32 of all index entries (crc32 of no bytes is 0) |
| 16     | 4    | bytes | end_magic    | `GOLS`                                 |

## Reading and corruption reporting

The reader accepts version 1 and version 2 files and returns the same API for
both. A file with the right magic and any other version raises
`UnsupportedVersionError`. Every structural problem raises `CorruptFileError`,
which now carries two attributes, `block_index` and `record_index` (each an
int or `None`):

* header problems (too short, bad `header_crc`, non-zero flags): both `None`;
  the message contains the word `header`.
* trailer and index problems (bad `end_magic`, trailer `block_count` differing
  from the header, a file length inconsistent with `index_offset`, bad
  `index_crc`): both `None`; the message contains the word `index`.
* an index entry that does not describe the block actually found
  (any field differs): `block_index` is that entry's block number,
  `record_index` is `None`; the message contains the word `index`.
* a block whose `block_crc` does not match, that runs past `index_offset`,
  whose payload ends partway through a record's fixed 21-byte part, or whose
  payload has bytes left over after its last record:
  `block_index` is the 0-based block number, `record_index` is `None`.
* a record with an unknown kind, unknown flag bits, quality above 100, a label
  that is not valid UTF-8, or a label running past the end of the payload:
  `block_index` is its block number, `record_index` is its file-wide 0-based
  index. A block's CRC is checked before its records are decoded, and records
  are decoded in order, so the first bad record is the one reported.
* the block record counts not summing to the header's `record_count`, or the
  blocks not ending exactly at `index_offset`: both `None`.

Messages for problems with a `block_index` start with `block <i>: `. Messages
with a `record_index` contain `record <j>` (j file-wide). For version 1
files `block_index` is always `None` and the existing checks are unchanged.

## API changes that come with version 2

These apply whatever version a file was read from.

* `Record` gains a sixth field, `quality: int = 100` (an int 0..100; bools are
  rejected). `Record.timestamp` is now **Unix epoch microseconds** (any value
  that fits in an i64). Records read from a version 1 file have
  `timestamp = seconds * 1_000_000` and `quality = 100`.
* `LogReader.created` is in microseconds (version 1: `created * 1_000_000`).
  `LogReader.block_count` is the header's block count, or `None` for a
  version 1 file. `LogReader.version` is the on-disk version.
* `write_log(path, records, station="", created=None, version=2, block_size=256)`
  writes version 2 by default. `created` is microseconds (default: now).
  `version=1` writes the version 1 format byte for byte as before;
  any other version raises `UnsupportedVersionError`. `block_size` must be at
  least 1 (else `ValueError`) and is ignored for version 1. If `write_log`
  raises, no file is left at `path`, and a file already there is unchanged.
* Writing version 1 raises `NotRepresentableError` (new, exported from
  `senslog`, subclass of both `SenslogError` and `ValueError`) when the data
  cannot be stored in version 1 exactly. It has attributes `record_index`
  (0-based, or `None` for a header field) and `field` (one of `"station"`,
  `"created"`, `"timestamp"`, `"label"`, `"quality"`). Header fields are
  checked first (station, then created), then records in order; within a
  record, timestamp, then label, then quality. The first failure found is
  raised. A value is not representable when:
  * station or label: not latin-1 encodable, longer than its v1 width
    (16 / 24 bytes), or contains NUL;
  * created or timestamp: not a whole number of seconds, or the seconds do
    not fit in a u32;
  * quality: anything other than 100.
* Version 2 writing raises `ValueError` for a label or station longer than
  65535 UTF-8 bytes.
* `senslog.migrate(src, dst, block_size=256)` reads any readable SLOG file and
  writes it to `dst` as version 2 with the same station, created time and
  records, returning the number of records.
* Time text (`senslog.timefmt`): `format_ts(us)` gives
  `YYYY-MM-DDTHH:MM:SSZ` when the microsecond part is zero, else
  `YYYY-MM-DDTHH:MM:SS.ffffffZ` (always 6 digits); it must be exact for every
  value, so do not go through float seconds. `parse_ts(text)` returns
  microseconds and accepts both forms (the fraction may have 1 to 6 digits);
  a bare integer still means epoch **seconds**.
* CSV (`senslog.csvio`) gains a sixth column `quality` after `calibrated`.
  On import it is optional (3 to 6 columns) and defaults to 100.
* `senslog.stats`: `first_ts`/`last_ts` are microseconds; `span` is seconds
  as a float; `rate` is still readings per second.
* `ops.filter_records` gains `min_quality=None` (keep `quality >= min_quality`);
  `ops.dedupe` treats records differing only in quality as different.
* CLI:
  * `import`, `filter` and `merge` write version 2 by default and accept
    `--format-version {1,2}`; a `NotRepresentableError` exits with status 2.
  * `filter` gains `--min-quality N`.
  * new `migrate SRC DST [--block-size N]`: prints `migrated <n> records to <DST>`,
    exit 0.
  * `info` prints a `blocks: <n>` line after `records:` for version 2 files.
