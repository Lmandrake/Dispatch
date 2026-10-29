"""Business rules.

``Tracker`` is the only thing that should change a repository.  It acts on
behalf of one user (``actor``); every public mutating method checks that
user's permissions, validates its input, applies the change, records audit
events and commits.  If anything raises part-way through, the repository is
rolled back so no partial change (or stray audit event) survives.

The class is assembled from mixins, one module per area:

=====================  ==============================================
module                 methods
=====================  ==============================================
services/base.py       transactions, permission helpers, lookups
services/users.py      add_user, deactivate_user, reactivate_user, ...
services/projects.py   create_project, archive, members, ...
services/issues.py     create_issue, update_issue, transition, ...
services/comments.py   add_comment, comments
services/bulk.py       bulk_transition, bulk_assign, bulk_label,
                       import_issues
services/queries.py    search, board, next_up, workload, ...
services/views.py      the ordered-issue cache used by queries
=====================  ==============================================
"""

from trellis.services.tracker import Tracker

__all__ = ["Tracker"]
