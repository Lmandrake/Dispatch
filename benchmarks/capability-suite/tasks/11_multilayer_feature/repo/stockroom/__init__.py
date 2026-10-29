"""stockroom: a small inventory and order tracker.

Layers, bottom to top:

* ``models``      dataclasses for items, orders and audit events
* ``storage``     the repository interface and two backends (memory, JSON file)
* ``query``       the filter mini-language used by ``list --where``
* ``audit``       the audit log written by every mutating service call
* ``services``    business rules and validation
* ``export`` / ``report``  CSV, JSON and text renderings
* ``cli``         the ``python3 -m stockroom`` command line
"""

__version__ = "1.4.0"
