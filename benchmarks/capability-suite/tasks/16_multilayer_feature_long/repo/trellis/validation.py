"""Input normalisation and validation.

Every ``check_*`` / ``normalize_*`` function either returns the cleaned value
or raises ``ValidationError``; none of them touch storage.
"""

import re

from trellis.dates import parse_date
from trellis.errors import ValidationError
from trellis.models import PRIORITIES, ROLES, STATUSES, TYPES, issue_key_parts

_USERNAME = re.compile(r"^[a-z][a-z0-9_.]{1,31}$")
_PROJECT_KEY = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")
_LABEL = re.compile(r"^[a-z0-9][a-z0-9_-]{0,23}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

MAX_TITLE = 120
MAX_DESCRIPTION = 10_000
MAX_COMMENT = 5_000
MAX_LABELS = 12
MAX_ESTIMATE = 1000


def normalize_username(text):
    if not isinstance(text, str):
        raise ValidationError(f"bad username {text!r}")
    name = text.strip().lower()
    if not _USERNAME.match(name):
        raise ValidationError(
            f"bad username {text!r}: 2-32 chars, a letter first, then letters, digits, _ or ."
        )
    return name


def normalize_project_key(text):
    if not isinstance(text, str):
        raise ValidationError(f"bad project key {text!r}")
    key = text.strip().upper()
    if not _PROJECT_KEY.match(key):
        raise ValidationError(f"bad project key {text!r}: 2-10 letters/digits, a letter first")
    return key


def normalize_issue_key(text):
    if not isinstance(text, str):
        raise ValidationError(f"bad issue key {text!r}")
    raw = text.strip().upper()
    try:
        project, number = issue_key_parts(raw)
    except ValueError:
        raise ValidationError(f"bad issue key {text!r}: want e.g. WEB-12") from None
    project = normalize_project_key(project)
    if number < 1:
        raise ValidationError(f"bad issue key {text!r}")
    return f"{project}-{number}"


def check_display_name(text):
    name = (text or "").strip()
    if not name or len(name) > 80:
        raise ValidationError("display name must be 1-80 characters")
    return name


def check_email(text):
    email = (text or "").strip()
    if email and not _EMAIL.match(email):
        raise ValidationError(f"bad email address {text!r}")
    return email


def check_project_name(text):
    name = (text or "").strip()
    if not name or len(name) > 80:
        raise ValidationError("project name must be 1-80 characters")
    return name


def check_title(text):
    if not isinstance(text, str):
        raise ValidationError("title must be text")
    title = " ".join(text.split())
    if not title:
        raise ValidationError("title must not be empty")
    if len(title) > MAX_TITLE:
        raise ValidationError(f"title is longer than {MAX_TITLE} characters")
    return title


def check_description(text):
    text = text or ""
    if not isinstance(text, str):
        raise ValidationError("description must be text")
    if len(text) > MAX_DESCRIPTION:
        raise ValidationError(f"description is longer than {MAX_DESCRIPTION} characters")
    return text.strip()


def check_comment(text):
    body = (text or "").strip()
    if not body:
        raise ValidationError("comment must not be empty")
    if len(body) > MAX_COMMENT:
        raise ValidationError(f"comment is longer than {MAX_COMMENT} characters")
    return body


def check_role(text):
    role = (text or "").strip().lower()
    if role not in ROLES:
        raise ValidationError(f"unknown role {text!r}; use one of {', '.join(ROLES)}")
    return role


def check_status(text):
    status = (text or "").strip().lower().replace("-", "_")
    if status not in STATUSES:
        raise ValidationError(f"unknown status {text!r}; use one of {', '.join(STATUSES)}")
    return status


def check_priority(text):
    p = (text or "").strip().lower()
    if p not in PRIORITIES:
        raise ValidationError(f"unknown priority {text!r}; use one of {', '.join(PRIORITIES)}")
    return p


def check_type(text):
    t = (text or "").strip().lower()
    if t not in TYPES:
        raise ValidationError(f"unknown issue type {text!r}; use one of {', '.join(TYPES)}")
    return t


def check_due(text):
    """``""`` / None clears; otherwise a strict YYYY-MM-DD date."""
    if text is None or text == "":
        return ""
    return parse_date(text).isoformat()


def check_estimate(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValidationError(f"bad estimate {value!r}")
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"bad estimate {value!r}") from None
    if n != value and not isinstance(value, str):
        raise ValidationError(f"bad estimate {value!r}")
    if not 0 <= n <= MAX_ESTIMATE:
        raise ValidationError(f"estimate must be 0..{MAX_ESTIMATE}")
    return n


def normalize_label(text):
    if not isinstance(text, str):
        raise ValidationError(f"bad label {text!r}")
    label = text.strip().lower()
    if not _LABEL.match(label):
        raise ValidationError(f"bad label {text!r}: 1-24 chars of a-z 0-9 _ -, not starting with _ or -")
    return label


def normalize_labels(labels):
    """A sorted, de-duplicated tuple of normalised labels."""
    if isinstance(labels, str):
        labels = [labels]
    out = sorted({normalize_label(t) for t in labels or ()})
    if len(out) > MAX_LABELS:
        raise ValidationError(f"an issue can have at most {MAX_LABELS} labels")
    return tuple(out)
