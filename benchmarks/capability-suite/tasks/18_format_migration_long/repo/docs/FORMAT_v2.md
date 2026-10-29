# Archive format version 2 (columnar)

Version 2 stores each column as one contiguous block, adds the `bool` type,
UTF-8 text and a metadata map, and protects the header and every column block
with its own CRC. It is the format written by default today.

All integers are little-endian; there is no padding or alignment. "crc32"
means `zlib.crc32(data) & 0xFFFFFFFF`. A "u16 string" is a u16 byte length
followed by that many UTF-8 bytes.

## Layout

```
header
column block 0 .. column block (column_count - 1)
end magic        4 bytes  "RAST"
```

## Header

| offset | size | type   | field          | notes                                 |
|-------:|-----:|--------|----------------|---------------------------------------|
| 0      | 4    | bytes  | magic          | `TSAR`                                |
| 4      | 2    | u16    | version        | 2                                     |
| 6      | 2    | u16    | flags          | must be 0                             |
| 8      | 4    | u32    | row_count      |                                       |
| 12     | 2    | u16    | column_count   |                                       |
| 14     | 2    | u16    | metadata_count |                                       |
| 16     | ...  |        | metadata       | `metadata_count` pairs of u16 strings (key, value), in insertion order |
| ...    | 4    | u32    | header_crc     | crc32 of the header bytes before it   |

## Column block

| size | type   | field     | notes                                          |
|-----:|--------|-----------|------------------------------------------------|
| 1    | u8     | type      | 1 = ts, 2 = int, 3 = float, 4 = str, 5 = bool  |
| 1+n  |        | name      | u8 length, then ASCII bytes                    |
| 4    | u32    | data_len  |                                                |
| n    | bytes  | data      | see below                                      |
| 4    | u32    | data_crc  | crc32 of `data`                                |

Column data, for `row_count` values:

* `ts`, `int`: i64 per value; `float`: f64 per value.
* `str`: `row_count` u32 **end** offsets (the end of each string, relative to
  the first string byte), then the concatenated UTF-8 bytes.
* `bool`: a packed bitmap, **most significant bit first**: value `i` is bit
  `7 - i % 8` of byte `i // 8`; unused bits of the last byte are zero.

## Validation

`ChecksumError` for a bad header or column CRC; `FormatError` for unknown
flags or type codes, a column whose data length does not fit its type, bad
string offsets, invalid UTF-8, non-zero bitmap padding, a bad end magic or
bytes after it.
