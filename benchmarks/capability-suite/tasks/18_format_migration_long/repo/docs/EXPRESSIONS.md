# Filter expressions

`tsarc query --where EXPR` and `ArchiveReader.query(where=EXPR)` keep the rows
for which `EXPR` is true. The grammar is in the docstring of `tsarc.expr`.

## Values and types

* Column names refer to the row's value in that column.
* Numbers: `42`, `-3`, `2.5`, `1e-3`. Text: `'roof'` or `"roof"` (backslash escapes `\n`, `\t`, `\\`, `\'`, `\"`).
* `true`, `false`.
* A text literal compared with a `ts` value is parsed as a timestamp:
  `ts >= '2026-03-01T06:00:00Z'`, `ts between '2026-03-01' and '2026-03-02'`.

## Operators

| operator                     | meaning                                                  |
|------------------------------|----------------------------------------------------------|
| `+ - * / %`                  | arithmetic; `/` is always float; division by zero gives NaN (`%` by zero gives 0 for ints) |
| `= == != < <= > >=`          | comparison (text compares by code point)                  |
| `~`                          | regular-expression search: `site ~ '^ro'`                 |
| `x in (a, b, c)`             | membership in a literal list                              |
| `x between a and b`          | `a <= x <= b`                                             |
| `and`, `or`, `not`           | boolean logic                                             |

## Functions

`abs(x)`, `round(x)`, `isnan(x)`, `len(s)`, `lower(s)`, `upper(s)`,
`startswith(s, p)`, `endswith(s, p)`, `contains(s, p)`, and the time parts
`year(t)`, `month(t)`, `day(t)`, `hour(t)`, `minute(t)`, `second(t)`,
`weekday(t)` (Monday = 0), `epoch_seconds(t)`; all UTC.

## Errors

Parse and type errors raise `ExpressionError` with a `position` (0-based
character offset); the CLI prints them and exits with status 2.
