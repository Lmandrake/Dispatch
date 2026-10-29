# Recurring issues

Status: **agreed design, not implemented yet.**  This document is the
specification; where it and the code disagree after implementation, the
code is wrong.

A recurring issue is an ordinary issue with a *recurrence rule* such as
`every 2 weeks on mon,thu until 2027-01-01`.  When the issue is closed, the
next occurrence is created automatically as a new issue with the next due
date.  Each occurrence is a separate issue with its own key, comments and
history; the series is the chain of `spawned_from` links.

## 1. Data

Two new `Issue` fields, both strings with default `""`:

| field | meaning |
|---|---|
| `recurrence` | the rule, always stored in canonical form (section 3); `""` = not recurring |
| `spawned_from` | key of the occurrence this issue was spawned from (`"WEB-3"`); `""` otherwise |

A recurring issue always has a due date: setting a rule on an issue without
one is a `ValidationError`, and so is clearing the due date of a recurring
issue (`update_issue(key, due="")`) or moving it past the rule's `until`
date.  Moving it to another date within the rule is fine; the stored rule
does not change (it is canonical, so it already names its weekdays or
month day).

## 2. Grammar

Input is case-insensitive; any run of whitespace counts as one space, and
spaces are allowed around commas.

    rule     := "every" [count] unit [on] [until]
              | "every" "weekday" [until]
    count    := an integer 1..99 written in digits
    unit     := "day" | "days" | "week" | "weeks" | "month" | "months"
    on       := "on" weekdays          -- week units only
              | "on" monthday          -- month units only
    weekdays := weekday ( "," weekday )*
    weekday  := mon | tue | wed | thu | fri | sat | sun
              | monday | tuesday | wednesday | thursday | friday | saturday | sunday
    monthday := an integer 1..31 | "last"
    until    := "until" DATE           -- YYYY-MM-DD, inclusive

* Singular and plural units are interchangeable on input (`every 2 week`,
  `every weeks` are fine); an omitted count is 1.
* `every weekday` means `every week on mon,tue,wed,thu,fri`.
* A weekday may be repeated (`on mon,mon`); duplicates are dropped.
* Errors (all `ValidationError`, nothing changes): anything not matching the
  grammar, a count of 0 or above 99, an `on` clause with a day unit, a
  weekday list with a month unit or a month day with a week unit, more than
  one month day, an empty or trailing-comma weekday list, a month day
  outside 1..31, an impossible `until` date, an `until` date before the
  issue's current due date, and extra text after the rule.

## 3. Canonical form

Rules are stored, shown, exported and compared in canonical form.  The
canonical form is built from the parsed rule and the issue's due date *at
the time the rule is set*:

    "every" [" " N] " " UNIT [" on " DAYS] [" until " DATE]

* `N` is written only when it is greater than 1; `UNIT` is singular when
  N is 1 and plural otherwise: `every day`, `every 3 days`, `every week on
  mon`, `every 2 weeks on mon,thu`, `every month on 15`, `every 6 months
  on last`.
* Week rules always have an `on` clause: the listed weekdays as
  three-letter names, Monday-first order, joined by `,` with no spaces.
  When the input has no `on` clause the weekday of the due date is used
  (`every 2 weeks` set on an issue due on a Thursday becomes `every 2 weeks
  on thu`).
* Month rules always have an `on` clause: the month day as a number, or
  `last`.  When the input has none, the day number of the due date is used
  (`every month` on an issue due 2026-01-31 becomes `every month on 31`;
  due 2026-02-28 gives `every month on 28`, *not* `last`).
* Day rules never have an `on` clause.
* `until` is written as `YYYY-MM-DD`.

Canonicalising a canonical rule returns it unchanged.

## 4. The series and the next due date

All arithmetic is on calendar dates (`datetime.date`).  There are no times
and no time zones, so daylight-saving changes cannot shift anything: one day
after 2026-03-08 is 2026-03-09, always.

The *series* of an occurrence due on date D:

* **days**, `every N days`: D + N days, D + 2N days, ...
* **weeks**, `every N weeks on W1,W2,...`: take the Monday-to-Sunday week
  containing D, and every Nth week after it (week 0, week N, week 2N, ...);
  the series dates are the listed weekdays of those weeks.
* **months**, `every N months on M`: take the month containing D and every
  Nth month after it; in each, the series date is day M, or the last day of
  the month when the month is shorter than M (or when M is `last`).  The
  day is taken from the rule each time, never from the previous
  occurrence: `every month on 31` from 2026-01-31 runs 02-28, 03-31,
  04-30, ...  (`trellis.dates.add_months` clamps lossily and must not be
  chained for this.)

The *next date after D* is the earliest series date strictly after D.
Examples: `every 2 weeks on mon,thu` after Monday 2026-05-04 is Thursday
2026-05-07, and after Thursday 2026-05-07 is Monday 2026-05-18; `every month
on 15` after 2026-01-10 is 2026-01-15; `every 12 months on 29` after
2024-02-29 is 2025-02-28 and after that 2026-02-28.

The **next due date** when an occurrence due on D is closed on date T
(today, from the clock):

1. N = the next date after D.
2. While N is before T: N = the next date after N.  (Missed occurrences are
   skipped, not created.  A next due date equal to T is fine.)
3. If the rule has `until U` and N is after U, the series has ended:
   nothing is spawned.

## 5. Spawning

When an issue with a non-empty `recurrence` moves to `done` **or**
`wontfix` (by `transition`, `close`, or `bulk_transition`), and no issue
anywhere has `spawned_from` equal to its key, the next occurrence is
created in the same transaction, in the same project, with the project's
next issue number.  Closing an occurrence a second time (after a reopen)
therefore never spawns a second successor, unless that successor has been
deleted.  Deleting a recurring issue spawns nothing.

The new occurrence:

| field | value |
|---|---|
| project, title, description, type, priority, labels, estimate, reporter, recurrence | copied from the closed occurrence |
| assignee | copied if that user can still be assigned in the project (active, role member or admin); otherwise `""` |
| watchers | the closed occurrence's watchers that are still members of the project (any role) and active users |
| due | the next due date (section 4) |
| status | `open` |
| spawned_from | the closed occurrence's key |
| created_at, updated_at | now; `closed_at` is `""` |
| comments | none |

Audit events, in this order: the closed occurrence's `issue.transitioned`
event as today, then `issue.created` for the new occurrence with the
usual details (title, type, priority, and assignee / due / labels /
estimate when set) plus `recurrence` and `spawned_from`.  Both events have
the closing user as actor.  When the series has ended no extra event is
recorded.

## 6. Service API (`Tracker`)

* `create_issue(..., recurrence="")`: a non-empty rule is canonicalised
  against the new issue's due date; the `issue.created` event gets a
  `recurrence` detail only when the rule is set (so existing events look
  exactly as before).
* `set_recurrence(key, rule)`: set, change or (with `""` or `None`) clear
  the rule; returns the updated issue.  Setting or changing needs an open
  issue with a due date (`ValidationError` otherwise); clearing works on
  any issue.  Records one `issue.recurrence_changed` event with details
  `{"from": <old canonical rule or "">, "to": <new canonical rule or "">}`
  and bumps `updated_at`.  When the canonical rule does not change: no
  change, no event, `updated_at` untouched.
* `successor(key)`: the issue spawned from `key`, or `None`.
* `update_issue` still does not accept `recurrence` or `spawned_from`.
* `import_issues` rows may carry `recurrence` (a rule; needs `due` in the
  same row).  The `issue.created` event of such a row has the `recurrence`
  detail too.

The rule functions live in a new module `trellis/recurrence.py`:

* `canonicalize(text, due)`: the canonical form of `text` for an issue due
  on `due` (`YYYY-MM-DD`); `ValidationError` for a bad rule (including an
  `until` before `due`).
* `next_due(rule, due, today=None)`: the next due date (`YYYY-MM-DD`) of
  section 4 for an occurrence due on `due` closed on `today` (no catch-up
  when `today` is None), or `None` when the series has ended.  `rule` may be
  any valid rule text; it is canonicalised against `due` first, except that
  an `until` before `due` is not an error here (the result is simply
  `None`).

## 7. Permissions

| operation | viewer | member | admin |
|---|---|---|---|
| set, change or clear a recurrence | - | only on issues they reported or are assigned | yes |
| close a recurring issue (spawns) | - | yes | yes |
| create an issue with a recurrence | - | yes (they are the reporter) | yes |

A member who is neither the reporter nor the assignee gets
`PermissionDenied` from `set_recurrence`.  The system user may do
everything.  Archived projects stay read-only.

## 8. Storage

* JSON format **version 5**: every issue record gets `"recurrence"` and
  `"spawned_from"` keys (strings), appended after `"closed_at"`.  Files of
  versions 1 to 4 still load (their issues get `""` for both) and are
  written back as version 5 on the next commit; a file newer than 5 is
  refused.
* SQLite schema **version 5**: columns `recurrence TEXT NOT NULL DEFAULT ''`
  and `spawned_from TEXT NOT NULL DEFAULT ''` on `issues`.  Databases of
  versions 1 to 4 upgrade on open; a fresh database and an upgraded one
  must have identical tables and columns.
* Both backends must keep behaving identically, including after rollback
  (a failed `bulk_transition` that spawned an occurrence before failing
  must leave no trace of it: no issue, no number used, no events).
* Add `tests/data/legacy_v4.json` / `legacy_v4.db` style fixtures of the
  version you are leaving if the existing ones do not already cover it.

## 9. Query language

| field | alias | type | meaning |
|---|---|---|---|
| `recurring` | | bool | has a recurrence rule |
| `recurrence` | `repeats` | text | the canonical rule (`""` when none) |
| `spawned` | | bool | `spawned_from` is set |
| `spawned_from` | `previous` | text | the key it was spawned from |

So `recurring and due < +7d`, `repeats ~ month`, `previous = web-3`.

## 10. Output

* `create ... --repeat RULE` sets a rule at creation (needs `--due`).
* New command `repeat ISSUE RULE` sets or changes the rule; `repeat ISSUE
  none` (or `-`) clears it.  Output: `WEB-4: repeats every week on mon`, or
  `WEB-4: does not repeat`.
* `move`, `close` and `bulk move`: after the usual output, one line
  `spawned WEB-9 due 2026-05-18` for every occurrence spawned by the
  command, in the order the issues were given.  When `move`/`close` closes
  a recurring issue that has no successor yet and its series has ended, the
  line `WEB-4: series ended` is printed instead.  Nothing extra is printed
  when no spawn was due (not recurring, not closing, or a successor already
  exists).
* `show` prints `Repeats:    <rule>` (`-` when none) directly after the
  `Due:` line, and `Previous:   <key>` directly after that, only when
  `spawned_from` is set.  `show --json` gets the two new keys like the JSON
  export.
* Issue CSV export: columns `recurrence,spawned_from` appended after
  `closed`.  Issue JSON export: keys `recurrence`, `spawned_from` appended
  after `closed_at`.  The text table is unchanged.
* CSV import accepts an optional `recurrence` column; `spawned_from` is
  accepted and ignored (like the other export-only columns).
* `agenda` gets a `Repeats` column between `Assignee` and `Title`: the rule,
  or `-`.  The `due` report gets the same column in the same place.
* New report `recurring` (all readable projects, or `-P KEY`): columns
  `Key`, `Due`, `Rule`, `Next`, `Assignee`; one row per *open* recurring
  issue, in (due, project, number) order; `Next` is `next_due(rule, due,
  today)`, or `ends` when the series would end; `-` for no assignee.  All
  columns are left-aligned (`render_table` defaults), and the report ends
  with a newline like the others.  With no open recurring issues the
  report is the line `No recurring issues.`
* The digest's Overdue and Due soon lines for recurring issues end with
  `  (repeats)` (two spaces).
* `show --timeline`: `issue.recurrence_changed` reads `ana set the
  recurrence to every week on mon`, or `ana cleared the recurrence`; an
  `issue.created` event with `spawned_from` reads `ana created the issue
  (spawned from WEB-3)`.
* `db check` also reports, with the issue key as the subject like its
  other issue checks, `recurring but has no due date` and `recurrence
  '<rule>' is not canonical` (the rule differs from `canonicalize(rule,
  due)`, or cannot be parsed), e.g. `WEB-4: recurring but has no due date`.
