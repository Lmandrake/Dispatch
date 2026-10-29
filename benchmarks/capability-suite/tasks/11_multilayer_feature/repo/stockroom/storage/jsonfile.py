"""JSON-file repository.

The whole database is one JSON document::

    {
      "version": 2,
      "next_order_id": 4,
      "items":  [ {"sku": ..., "name": ..., ...}, ... ],
      "orders": [ {"id": 1, "sku": ..., ...}, ... ],
      "events": [ {"seq": 1, "timestamp": ..., ...}, ... ]
    }

The file is read once when the repository is opened; changes are kept in
memory and written back atomically (temp file + rename) on ``commit()``.
``rollback()`` discards uncommitted changes.

Format history
--------------
* version 1: items had ``bin`` instead of ``location`` and no
  ``reorder_level``; there was no ``next_order_id`` key.
* version 2 (current): as above.

Older files are migrated in memory when loaded and written back in the
current format on the next commit.  A file whose version is newer than
``FORMAT_VERSION`` is refused rather than silently mangled.
"""

import json
import os
import tempfile

from stockroom.errors import StorageError
from stockroom.models import AuditEvent, Item, Order
from stockroom.storage.memory import MemoryRepository

FORMAT_VERSION = 2


# ---- (de)serialisation ---------------------------------------------------

def item_to_dict(item):
    return {
        "sku": item.sku,
        "name": item.name,
        "quantity": item.quantity,
        "price_cents": item.price_cents,
        "location": item.location,
        "reorder_level": item.reorder_level,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def item_from_dict(d):
    try:
        return Item(
            sku=d["sku"],
            name=d["name"],
            quantity=int(d.get("quantity", 0)),
            price_cents=int(d.get("price_cents", 0)),
            location=d.get("location", ""),
            reorder_level=int(d.get("reorder_level", 0)),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise StorageError(f"bad item record {d!r}: {exc}") from None


def order_to_dict(order):
    return {
        "id": order.id,
        "sku": order.sku,
        "quantity": order.quantity,
        "customer": order.customer,
        "status": order.status,
        "created_at": order.created_at,
        "closed_at": order.closed_at,
    }


def order_from_dict(d):
    try:
        return Order(
            id=int(d["id"]),
            sku=d["sku"],
            quantity=int(d["quantity"]),
            customer=d.get("customer", ""),
            status=d.get("status", "open"),
            created_at=d.get("created_at", ""),
            closed_at=d.get("closed_at", ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise StorageError(f"bad order record {d!r}: {exc}") from None


def event_to_dict(event):
    return {
        "seq": event.seq,
        "timestamp": event.timestamp,
        "action": event.action,
        "subject": event.subject,
        "details": event.details,
    }


def event_from_dict(d):
    try:
        return AuditEvent(
            seq=int(d["seq"]),
            timestamp=d["timestamp"],
            action=d["action"],
            subject=d["subject"],
            details=dict(d.get("details") or {}),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise StorageError(f"bad event record {d!r}: {exc}") from None


# ---- migrations ------------------------------------------------------------

def _migrate_v1_to_v2(doc):
    items = []
    for d in doc.get("items", []):
        d = dict(d)
        if "bin" in d:
            d["location"] = d.pop("bin") or ""
        d.setdefault("reorder_level", 0)
        items.append(d)
    doc = dict(doc)
    doc["items"] = items
    orders = doc.get("orders", [])
    doc.setdefault("next_order_id", max([0] + [int(o["id"]) for o in orders]) + 1)
    doc["version"] = 2
    return doc


MIGRATIONS = {
    1: _migrate_v1_to_v2,
}


def migrate(doc):
    """Bring a loaded document up to FORMAT_VERSION, one step at a time."""
    version = doc.get("version", 1)
    if not isinstance(version, int) or version < 1:
        raise StorageError(f"bad format version: {version!r}")
    if version > FORMAT_VERSION:
        raise StorageError(
            f"data file has format version {version}; this stockroom "
            f"only understands up to version {FORMAT_VERSION}"
        )
    while version < FORMAT_VERSION:
        step = MIGRATIONS.get(version)
        if step is None:
            raise StorageError(f"no migration from format version {version}")
        doc = step(doc)
        version = doc["version"]
    return doc


# ---- the repository ----------------------------------------------------------

class JsonFileRepository(MemoryRepository):
    def __init__(self, path):
        super().__init__()
        self.path = os.fspath(path)
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            self._load_state([], [], [], 1)
            return
        try:
            with open(self.path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            raise StorageError(f"cannot read {self.path}: {exc}") from None
        if not isinstance(doc, dict):
            raise StorageError(f"{self.path}: top level must be an object")
        doc = migrate(doc)
        self._load_state(
            [item_from_dict(d) for d in doc.get("items", [])],
            [order_from_dict(d) for d in doc.get("orders", [])],
            [event_from_dict(d) for d in doc.get("events", [])],
            int(doc.get("next_order_id", 1)),
        )

    def to_document(self):
        return {
            "version": FORMAT_VERSION,
            "next_order_id": self._next_order_id,
            "items": [item_to_dict(i) for i in self.list_items()],
            "orders": [order_to_dict(o) for o in self.list_orders()],
            "events": [event_to_dict(e) for e in self.list_events()],
        }

    def commit(self):
        doc = self.to_document()
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".stockroom-", suffix=".json", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, indent=2, sort_keys=False)
                fh.write("\n")
            os.replace(tmp, self.path)
        except OSError as exc:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise StorageError(f"cannot write {self.path}: {exc}") from None
        super().commit()
