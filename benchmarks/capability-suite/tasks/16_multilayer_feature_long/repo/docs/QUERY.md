# The `--where` query language

    trellis list --where 'status != done and (priority >= high or overdue)'
    trellis list -w 'assignee = me label in (ui, auth)'
    trellis list -w 'due < +7d and not unassigned'

## Grammar

    query      := or_expr
    or_expr    := and_expr ( "or" and_expr )*
    and_expr   := unary ( ["and"] unary )*     -- juxtaposition means "and"
    unary      := "not" unary | primary
    primary    := "(" or_expr ")" | comparison
    comparison := FIELD OP value | FIELD "in" "(" value ("," value)* ")" | BOOLFIELD
    OP         := = | != | < | <= | > | >= | ~

`not` binds tightest, then `and`, then `or`.  Keywords and field names are
case-insensitive.  Values are bare words (letters, digits and `_ - . / + :
@`) or quoted strings (`"..."` or `'...'`, backslash escapes the quote).
An empty query matches everything.  `trellis explain QUERY` shows how a
query was parsed; `trellis explain --fields` lists every field.

## Fields

| field | aliases | type |
|---|---|---|
| key, project, title, description | | text |
| number, estimate | est | int |
| type, status | | enum |
| priority | pri | ordered enum (low < normal < high < urgent) |
| assignee, reporter | who (assignee) | user |
| label, watcher | labels, tag; watchers | list |
| due, created, updated, closed | deadline (due) | date |
| open, overdue, unassigned, mine | | bool |

`overdue`: open, has a due date, and the due date is before today.
`mine`: assigned to the acting user (`--as`).

## Types

* **text**: `=`, `!=`, `in` compare whole values, `~` is a substring
  test; all are case-insensitive.
* **enum**: `=`, `!=`, `in`; an unknown choice is an error.  The ordered
  enum `priority` also takes `< <= > >=`.
* **int**: the usual comparisons; `none` means "no value" (`estimate =
  none`).  An issue without a value never matches `= < <= > >= in` and
  always matches `!=` (except `!= none`).
* **date**: like int, with values `YYYY-MM-DD`, `today`, `tomorrow`,
  `yesterday`, `+3d`, `-2w`, `+1m`.
* **user**: `=`, `!=`, `in`; `me` is the acting user, `none` is nobody.
* **list**: `= X` has X; `!= X` lacks X; `in (X, Y)` has at least one;
  `~ X` some value contains X.
* **bool**: bare (`overdue`), `not overdue`, or `= true/false/yes/no/1/0`.

Any other operator on a field is a `QueryError` naming the field and the
operators it allows.
