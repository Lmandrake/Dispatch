"""In-memory repository.

Used by the tests and by ``--db :memory:``.  It keeps a secondary index of
SKUs by location so ``items_at`` does not scan every item, and supports
``commit``/``rollback`` by snapshotting its state at each commit.
"""

from stockroom.storage.base import Repository


class MemoryRepository(Repository):
    def __init__(self):
        self._items = {}
        self._orders = {}
        self._events = []
        self._next_order_id = 1
        self._by_location = {}
        self._snapshot = self._take_snapshot()

    # ---- snapshots ---------------------------------------------------
    def _take_snapshot(self):
        return (
            dict(self._items),
            dict(self._orders),
            list(self._events),
            self._next_order_id,
            {loc: set(skus) for loc, skus in self._by_location.items()},
        )

    def commit(self):
        self._snapshot = self._take_snapshot()

    def rollback(self):
        items, orders, events, next_id, by_loc = self._snapshot
        self._items = dict(items)
        self._orders = dict(orders)
        self._events = list(events)
        self._next_order_id = next_id
        self._by_location = {loc: set(skus) for loc, skus in by_loc.items()}

    # ---- index maintenance -------------------------------------------
    def _unindex(self, item):
        skus = self._by_location.get(item.location)
        if skus is not None:
            skus.discard(item.sku)
            if not skus:
                del self._by_location[item.location]

    def _index(self, item):
        self._by_location.setdefault(item.location, set()).add(item.sku)

    # ---- items -------------------------------------------------------
    def get_item(self, sku):
        return self._items.get(sku)

    def list_items(self):
        return [self._items[k] for k in sorted(self._items)]

    def save_item(self, item):
        old = self._items.get(item.sku)
        if old is not None:
            self._unindex(old)
        self._items[item.sku] = item
        self._index(item)

    def delete_item(self, sku):
        old = self._items.pop(sku, None)
        if old is None:
            return False
        self._unindex(old)
        return True

    def items_at(self, location):
        """Items whose location is exactly ``location``, sorted by SKU."""
        return [self._items[s] for s in sorted(self._by_location.get(location, ()))]

    # ---- orders ------------------------------------------------------
    def get_order(self, order_id):
        return self._orders.get(order_id)

    def list_orders(self):
        return [self._orders[k] for k in sorted(self._orders)]

    def save_order(self, order):
        self._orders[order.id] = order
        if order.id >= self._next_order_id:
            self._next_order_id = order.id + 1

    def next_order_id(self):
        oid = self._next_order_id
        self._next_order_id += 1
        return oid

    # ---- audit -------------------------------------------------------
    def append_event(self, event):
        self._events.append(event)

    def list_events(self):
        return sorted(self._events, key=lambda e: e.seq)

    # ---- used by the JSON backend --------------------------------------
    def _load_state(self, items, orders, events, next_order_id):
        self._items = {}
        self._by_location = {}
        for item in items:
            self.save_item(item)
        self._orders = {o.id: o for o in orders}
        self._events = list(events)
        self._next_order_id = max([next_order_id] + [o.id + 1 for o in orders])
        MemoryRepository.commit(self)
