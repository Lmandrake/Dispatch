# Idempotency keys

A client that enqueues with `idempotency_key=K` and retries (lost response,
restarted process) must get back the same job id instead of creating a
second job. Keys are scoped to a queue.

## Canonical form

Keys are opaque client strings: order numbers, request ids, the scheduler's
`cron/<schedule>/<slot>`. Two keys are the same key when they are equal
after exactly these two steps, and no others:

1. Unicode normalisation to composed form (canonical composition, the "C"
   form; compatibility mappings such as ligatures or full-width digits are
   NOT applied);
2. stripping leading and trailing whitespace.

Case, punctuation, inner whitespace and every other character are
significant: `INV-12/3`, `inv-12/3` and `INV-1/23` are three keys. The
stored `Job.idempotency_key` and the output of `taskmill key` are the
canonical form.

A key must be 1-200 characters in canonical form, with no control
characters; otherwise `InvalidKey`.

## Lifetime

A key is held while its job is unfinished and for `dedup_window` seconds
after it finishes. After that, or once the job is purged, the key is free
again. An operator retry keeps the job's key.
