"""Customer-portal API: serializers, pagination and a tiny request router.

The portal front end asks for JSON documents; this package turns the
objects of a BillingRun into plain dicts (strings, ints, lists, dicts) that
``json.dumps`` accepts.  There is no HTTP server here: ``handle`` is a pure
function from a path and a query to ``(status, dict)`` so that any web
framework, or a test, can call it.
"""

from .pagination import Page, paginate
from .router import handle
from .serializers import (customer_dict, invoice_dict, invoice_summary_dict, plan_dict,
                          usage_summary_dict)

__all__ = ["Page", "paginate", "handle", "customer_dict", "invoice_dict", "invoice_summary_dict",
           "plan_dict", "usage_summary_dict"]
