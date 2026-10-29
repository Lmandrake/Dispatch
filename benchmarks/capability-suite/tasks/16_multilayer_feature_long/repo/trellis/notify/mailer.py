"""Turning a digest into an e-mail message (``digest --mail``).

trellis never sends mail itself; ``digest_message`` builds an
``email.message.EmailMessage`` that the caller can print (``--mail``
writes it to stdout in RFC 5322 form) or hand to an SMTP client.

Headers: ``To`` (the user's address, or an error if they have none),
``From`` (``TRELLIS_MAIL_FROM`` or ``trellis@localhost``), ``Subject``
(``[trellis] Digest for <user> (<date>): <n> item(s)``, where n counts
every entry in every section) and ``Date`` derived from the clock.  The body
is the rendered digest, plain text, UTF-8.
"""

import os
from email.message import EmailMessage
from email.utils import format_datetime

from trellis.clock import parse_timestamp
from trellis.errors import ValidationError
from trellis.notify.digest import render_digest

DEFAULT_FROM = "trellis@localhost"


def item_count(digest):
    return (len(digest.overdue) + len(digest.due_soon) + len(digest.activity)
            + digest.activity_dropped + len(digest.mentions))


def digest_message(digest, user, now, sender=None):
    if not user.email:
        raise ValidationError(f"{user.username} has no e-mail address")
    msg = EmailMessage()
    msg["To"] = f"{user.display_name} <{user.email}>"
    msg["From"] = sender or os.environ.get("TRELLIS_MAIL_FROM") or DEFAULT_FROM
    n = item_count(digest)
    msg["Subject"] = (f"[trellis] Digest for {digest.username} ({digest.today}): "
                      f"{n} item{'s' if n != 1 else ''}")
    msg["Date"] = format_datetime(parse_timestamp(now))
    msg.set_content(render_digest(digest))
    return msg
