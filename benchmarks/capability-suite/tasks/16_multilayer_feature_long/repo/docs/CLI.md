# Command reference

Global options: `--db PATH` (or `TRELLIS_DB`), `--as USER` (or
`TRELLIS_USER`; default the `system` superuser).  `TRELLIS_NOW` fixes the
clock.  Errors print `error: <message>` to stderr and exit 1; usage errors
exit 2.

## Users, projects, members

    user add USERNAME "Display Name" [--email E]      created user ana
    user list | user deactivate U | user reactivate U
    project create KEY "Name" [--description D] [--lead U]
    project list [--all] | project show KEY | project update KEY [--name] [--description] [--lead]
    project archive KEY | project unarchive KEY
    member add KEY USER ROLE | member role KEY USER ROLE | member remove KEY USER | member list KEY

## Issues

    create KEY "Title" [-d TEXT] [-t TYPE] [-p PRI] [-a USER] [-l LABEL]... [--due DATE] [-e N]
        -> created WEB-4
    edit ISSUE [--title] [-d] [-t] [-p] [--due DATE|none] [-e N|none]
        -> updated WEB-4   (or "WEB-4: no change")
    show ISSUE [--json] [--timeline]
    list [-P KEY] [-w QUERY] [--sort key|priority|due|updated|created|title] [--reverse]
         [--limit N] [-f table|csv|json]
    move ISSUE STATUS        -> WEB-4: in_progress
    close ISSUE [--wontfix]  -> WEB-4: done
    reopen ISSUE             -> WEB-4: open
    assign ISSUE USER|-      -> WEB-4: assigned to bob   ("nobody" for -)
    label ISSUE L...         -> WEB-4: labels auth, ui    ("no labels")
    unlabel ISSUE L...
    watch ISSUE [--user U]   -> WEB-4: watchers ana, bob
    unwatch ISSUE [--user U]
    comment ISSUE "text"     -> comment 7 added to WEB-4
    comments ISSUE
    delete ISSUE             -> deleted WEB-4
    bulk move STATUS ISSUE...   -> moved 3 issue(s) to done
    bulk assign USER ISSUE...   -> assigned 3 issue(s) to bob
    bulk label LABEL ISSUE...   -> labelled 3 issue(s) ui

`--due` accepts `YYYY-MM-DD`, `today`, `tomorrow`, `+3d`, `+2w`, `+1m`, ...

`show` prints, in this order: a `KEY  Title` line, then `Project:`,
`Type:`, `Status:`, `Priority:`, `Reporter:`, `Assignee:`, `Labels:`,
`Watchers:`, `Due:`, `Estimate:`, `Created:`, `Updated:`, `Closed:` lines
(values start in column 13; `-` for an empty value), then the
description and comments when there are any.

## Views

    board KEY                 open issues by status, in rank order
    next KEY [--user U] [--limit N]
    agenda [--days N] [--user U]
        table: Key, Due, In, Status, Assignee, Title   ("nothing due" when empty)
    history [--subject S] [--action A] [--actor U] [--since SEQ] [-P KEY] [--json]
    report [summary|status|labels|workload|due|velocity|aging] [-P KEY]
    stats KEY [--per-issue]
    explain QUERY | explain --fields
    digest [--user U] [--mark] [--all] [--mail]

## Data

    export issues|comments|events [-f csv|json|table] [-P KEY] [-w QUERY] [-o FILE]
    import KEY FILE.csv       -> imported 3 issue(s): WEB-5 .. WEB-7
    db info | db upgrade | db check | db copy DEST

See `trellis/export.py` for the exact columns and `trellis/importer.py`
for what import accepts.
