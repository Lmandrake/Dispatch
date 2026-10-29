"""Exception hierarchy.

Everything taskmill raises on purpose derives from :class:`TaskmillError`, so
callers (the admin API, the CLI) can map errors to responses in one place.
"""


class TaskmillError(Exception):
    """Base class for every error raised by taskmill on purpose."""

    status = 500  # HTTP-ish status used by the admin API


class ValidationError(TaskmillError, ValueError):
    """An argument is malformed (bad queue name, payload not JSON, ...)."""

    status = 400


class InvalidKey(ValidationError):
    """An idempotency key is empty, too long or contains control characters."""


class UnknownJob(TaskmillError, KeyError):
    """No job with that id."""

    status = 404

    def __str__(self) -> str:  # KeyError quotes its argument; we do not want that
        return self.args[0] if self.args else "unknown job"


class InvalidTransition(TaskmillError):
    """The requested operation is not allowed in the job's current state."""

    status = 409


class LeaseLost(TaskmillError):
    """The caller no longer holds the lease it presented.

    Raised by ``ack``, ``nack`` and ``heartbeat`` when the token is unknown,
    belongs to an earlier delivery of the job, or has passed its deadline.
    The worker must stop working on the job: it has been (or will be)
    redelivered to someone else.
    """

    status = 409


class ResultTooLarge(ValidationError):
    """An ack's result encodes to more than ``max_result_bytes``."""


class WalError(TaskmillError):
    """Base class for write-ahead-log problems."""


class WalCorrupt(WalError):
    """A record that is not the torn tail of the newest segment failed its checks."""


class SnapshotError(TaskmillError):
    """A snapshot file is unreadable or has an unsupported format."""


class BrokerClosed(TaskmillError):
    """The broker was closed; no further operations are accepted."""

    status = 503


class CronError(ValidationError):
    """A cron expression could not be parsed."""


class ConfigError(ValidationError):
    """A configuration value is out of range or of the wrong type."""


class HandlerNotFound(TaskmillError, LookupError):
    """No handler is registered for a job's kind."""

    status = 404


class PermanentError(Exception):
    """Raise from a handler to fail the job without further retries."""


class Retry(Exception):
    """Raise from a handler to retry after an explicit delay (seconds).

    The attempt still counts against ``max_attempts``.
    """

    def __init__(self, delay: float = None, reason: str = "retry requested"):
        super().__init__(reason)
        self.delay = delay
        self.reason = reason
