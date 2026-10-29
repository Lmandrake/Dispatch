# Billing periods and timestamps

## Timestamps

Usage timestamps are instants. Accepted forms: ISO 8601 with `Z` or a numeric offset (with or
without seconds and fractional seconds), epoch seconds, and epoch milliseconds (13 digits). A
timestamp without an offset is rejected; we never guess the zone of usage.

## Periods

Each customer is billed monthly from an anchor day (customers.csv `anchor_day`). Cycle
`YYYY-MM` is the period that starts in that month:

* anchor 1, cycle 2026-03: 1 March to 31 March;
* anchor 15, cycle 2026-03: 15 March to 14 April;
* anchors 29 to 31 clamp to the last day of shorter months.

A period is made of **local calendar days in the customer's timezone**. It starts at local
midnight at the beginning of its first day and ends at local midnight at the beginning of the
day after its last day. Both boundaries are local midnights, so a period that contains a
daylight-saving change is not a whole number of 24-hour days long: March 2026 in New York is
743 hours, October 2026 in Berlin is 745 hours. `BillingPeriod.start_utc` and
`BillingPeriod.end_utc` are those two local midnights expressed in UTC, and `hours()` is the
length between them.

A usage record belongs to the period when `start_utc <= at < end_utc`. A record stamped
00:20 local time on the first day of the next period belongs to the next period, however
its timestamp is written.

## Segments

When the plan changes inside a period the period is cut into segments at local midnight of
each change's effective day (docs/SUBSCRIPTIONS.md). Usage is assigned to the segment whose
local days contain it.

## Issue and due dates

An invoice is issued on the day after the period's last day; it is due `terms_days` later,
moved to the next Monday when that is a Saturday or Sunday.
