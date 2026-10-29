# SLOG file format, version 1

A SLOG file stores a station's sensor readings. All integers are
little-endian. Offsets are in bytes from the start of the file.

## Layout

```
header      32 bytes
records     record_count x 40 bytes
checksum    4 bytes
```

## Header (32 bytes)

| offset | size | type   | field        | notes                                   |
|-------:|-----:|--------|--------------|-----------------------------------------|
| 0      | 4    | bytes  | magic        | `SLOG` (53 4C 4F 47)                    |
| 4      | 2    | u16    | version      | 1                                       |
| 6      | 2    | u16    | flags        | must be 0                               |
| 8      | 4    | u32    | record_count |                                         |
| 12     | 4    | u32    | created      | file creation time, Unix epoch seconds  |
| 16     | 16   | bytes  | station      | latin-1, right-padded with 0x00         |

## Record (40 bytes)

| offset | size | type   | field     | notes                                          |
|-------:|-----:|--------|-----------|------------------------------------------------|
| 0      | 2    | u16    | sensor    |                                                |
| 2      | 1    | u8     | kind      | 0 = signed 64-bit integer, 1 = IEEE-754 double |
| 3      | 1    | u8     | flags     | bit 0 = calibrated; other bits must be 0       |
| 4      | 4    | u32    | timestamp | Unix epoch seconds                             |
| 8      | 8    | i64/f64| value     | interpreted according to `kind`                |
| 16     | 24   | bytes  | label     | latin-1, right-padded with 0x00                |

Text fields may not contain NUL characters; trailing 0x00 bytes are padding.

## Checksum

The last 4 bytes are a u32: `zlib.crc32` of every preceding byte of the file
(header and all records).

## Validation

A reader rejects the file (`CorruptFileError`) if the magic is wrong, the
header flags are non-zero, the file length is not exactly
`32 + 40 * record_count + 4`, the checksum does not match, or a record has an
unknown kind or flag bit. A file with the right magic and an unknown version
raises `UnsupportedVersionError`.
