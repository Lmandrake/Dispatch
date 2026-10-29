"""The assembled service class."""

from trellis.services.base import SYSTEM, TrackerBase
from trellis.services.bulk import BulkMixin
from trellis.services.comments import CommentsMixin
from trellis.services.issues import IssuesMixin
from trellis.services.projects import ProjectsMixin
from trellis.services.queries import QueriesMixin
from trellis.services.users import UsersMixin


class Tracker(UsersMixin, ProjectsMixin, IssuesMixin, CommentsMixin, BulkMixin, QueriesMixin,
              TrackerBase):
    """Everything trellis can do, acting as one user.

    ``Tracker(repo)`` acts as the built-in ``system`` superuser;
    ``Tracker(repo, actor="ana")`` checks ana's roles on every call.
    """


__all__ = ["Tracker", "SYSTEM"]
