"""The ``--where`` search language.  See docs/QUERY.md for the user guide.

    pred = compile_query("status = open and priority >= high", today="2026-05-01", me="ana")
    hits = [i for i in issues if pred(i)]

``filter_issues(issues, text, today=..., me=...)`` does both steps.
"""

from trellis.query.compiler import compile_query, filter_issues
from trellis.query.parser import parse

__all__ = ["compile_query", "filter_issues", "parse"]
