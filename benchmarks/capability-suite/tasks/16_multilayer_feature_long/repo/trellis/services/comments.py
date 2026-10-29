"""Comments."""

from trellis import permissions as P
from trellis.models import Comment
from trellis.services.base import transactional
from trellis.textutil import mentions
from trellis.validation import check_comment


class CommentsMixin:
    @transactional
    def add_comment(self, key, body):
        issue = self._writable_issue(key)
        body = check_comment(body)
        comment = Comment(id=self.repo.next_comment_id(), issue=issue.key,
                          author="" if self.is_system else self.actor, body=body,
                          created_at=self.clock())
        self.repo.add_comment(comment)
        details = {"id": comment.id}
        mentioned = [u for u in mentions(body) if self.repo.get_membership(issue.project, u)]
        if mentioned:
            details["mentions"] = mentioned
        self.audit.record(self.actor, "comment.added", issue.key, **details)
        return comment

    def comments(self, key):
        issue = self._issue(key)
        self.require(issue.project, P.READ)
        return self.repo.list_comments(issue.key)
