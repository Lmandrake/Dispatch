# Archive format version 1 (row-oriented)

Version 1 is the original tsarc format. It stores rows one after another and
supports only the `ts`, `int`, `float` and `str` column types. It has no
metadata. Files are still produced on request (`--format-version 1`) for old
consumers, so the encoder must not change.

All integers are little-endian; there is no padding or alignment.

## Layout

| offset | size | type   | field        | notes                                        |
|-------:|-----:|--------|--------------|----------------------------------------------|
| 0      | 4    | bytes  | magic        | `TSAR`                                       |
| 4      | 2    | u16    | version      | 1                                            |
| 6      | 2    | u16    | flags        | must be 0                                    |
| 8      | 2    | u16    | column_count |                                              |
| 10     | 4    | u32    | row_count    |                                              |
| 14     | ...  |        | columns      | `column_count` column descriptors            |
| ...    | ...  |        | rows         | `row_count` rows                             |
| end-4  | 4    | u32    | crc          | `zlib.crc32` of every preceding byte          |

A column descriptor is a u8 type code (1 = ts, 2 = int, 3 = float, 4 = str)
followed by the column name as a u8 length and that many ASCII bytes.

A row is one value per column, in column order:

* `ts`, `int`: i64
* `float`: f64 (IEEE-754 double)
* `str`: u16 length followed by that many **latin-1** bytes

## Validation

The reader raises `ChecksumError` when the CRC does not match (this is
checked first), and `FormatError` for unknown flags, an unknown type code, a
truncated row, or bytes left over after the last row.

## Writing

`NotRepresentableError` is raised when the table or its metadata cannot be
stored: any metadata at all, a column of type `bool`, or text that is not
latin-1 encodable or longer than 65535 bytes. Checks run in this order:
metadata, then column types in schema order, then the text of each `str`
column in schema order, row by row.
