"""Per-user notifications.

``build_digest(tracker, username)`` collects what a user should hear about
since their last digest; ``render_digest`` turns that into plain text.  The
CLI's ``digest`` command prints it and, with ``--mark``, records that the
user has been brought up to date.  See ``trellis.notify.digest``.
"""

from trellis.notify.digest import Digest, build_digest, render_digest
from trellis.notify.cursor import load_cursor, save_cursor

__all__ = ["Digest", "build_digest", "render_digest", "load_cursor", "save_cursor"]
