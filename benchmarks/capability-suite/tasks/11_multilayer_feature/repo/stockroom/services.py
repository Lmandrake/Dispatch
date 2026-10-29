"""Business rules.

``InventoryService`` is the only thing that should mutate a repository.
Each public mutating method validates its input, applies the change,
records audit events, and commits; if anything raises part-way through,
the repository is rolled back so no partial change (or stray audit event)
survives.

Rules:

* SKUs are normalised to upper case and must look like ``BOLT-0042``.
* Quantities are integers in 0..1,000,000; prices are integer cents >= 0.
* ``available(sku)`` is on-hand quantity minus quantity reserved by open
  orders.  Placing an order needs enough *available* stock.
* Fulfilling an order takes its quantity out of stock; cancelling an open
  order releases the reservation.  Closed orders cannot change again.
* An item with open orders cannot be removed, and an adjustment may not
  push on-hand stock below what open orders have reserved.
"""

import functools

from stockroom.audit import AuditLog
from stockroom.clock import utc_now
from stockroom.errors import ConflictError, NotFoundError, ValidationError
from stockroom.models import ORDER_CANCELLED, ORDER_FULFILLED, ORDER_OPEN, Item, Order
from stockroom.query import compile_query
from stockroom.validation import (
    check_customer,
    check_location,
    check_name,
    check_price_cents,
    check_quantity,
    normalize_sku,
)

UPDATABLE_FIELDS = ("name", "price_cents", "location", "reorder_level")


def _transactional(method):
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            result = method(self, *args, **kwargs)
        except BaseException:
            self.repo.rollback()
            raise
        self.repo.commit()
        return result

    return wrapper


class InventoryService:
    def __init__(self, repo, clock=utc_now):
        self.repo = repo
        self.clock = clock
        self.audit = AuditLog(repo, clock)

    # ---- lookups -------------------------------------------------------
    def get(self, sku):
        sku = normalize_sku(sku)
        item = self.repo.get_item(sku)
        if item is None:
            raise NotFoundError(f"no such item: {sku}")
        return item

    def items(self, where=None):
        """Items matching the ``--where`` query text (all items if None)."""
        pred = compile_query(where or "")
        return [it for it in self.repo.list_items() if pred(it)]

    def reserved(self, sku):
        return sum(o.quantity for o in self.repo.open_orders_for(sku))

    def available(self, sku):
        item = self.get(sku)
        return item.quantity - self.reserved(item.sku)

    def low_stock(self):
        return [it for it in self.repo.list_items() if it.is_low]

    def order(self, order_id):
        order = self.repo.get_order(order_id)
        if order is None:
            raise NotFoundError(f"no such order: {order_id}")
        return order

    def orders(self, status=None, sku=None):
        out = self.repo.list_orders()
        if status is not None:
            if status not in (ORDER_OPEN, ORDER_FULFILLED, ORDER_CANCELLED):
                raise ValidationError(f"unknown order status {status!r}")
            out = [o for o in out if o.status == status]
        if sku is not None:
            sku = normalize_sku(sku)
            out = [o for o in out if o.sku == sku]
        return out

    # ---- items ---------------------------------------------------------
    @_transactional
    def add_item(self, sku, name, quantity=0, price_cents=0, location="", reorder_level=0):
        sku = normalize_sku(sku)
        if self.repo.has_item(sku):
            raise ConflictError(f"item already exists: {sku}")
        now = self.clock()
        item = Item(
            sku=sku,
            name=check_name(name),
            quantity=check_quantity(quantity),
            price_cents=check_price_cents(price_cents),
            location=check_location(location),
            reorder_level=check_quantity(reorder_level, "reorder level"),
            created_at=now,
            updated_at=now,
        )
        self.repo.save_item(item)
        self.audit.record("item.added", sku, name=item.name, quantity=item.quantity,
                          price_cents=item.price_cents, location=item.location)
        return item

    @_transactional
    def update_item(self, sku, **changes):
        """Change any of name, price_cents, location, reorder_level.

        Fields whose new value equals the old one are ignored; if nothing
        actually changes, no event is recorded and the item is returned as is.
        """
        item = self.get(sku)
        unknown = set(changes) - set(UPDATABLE_FIELDS)
        if unknown:
            raise ValidationError(f"cannot update field(s): {', '.join(sorted(unknown))}")
        checkers = {
            "name": check_name,
            "price_cents": check_price_cents,
            "location": check_location,
            "reorder_level": lambda v: check_quantity(v, "reorder level"),
        }
        diff = {}
        for key in UPDATABLE_FIELDS:
            if key not in changes or changes[key] is None:
                continue
            new = checkers[key](changes[key])
            old = getattr(item, key)
            if new != old:
                diff[key] = [old, new]
        if not diff:
            return item
        updated = item.with_changes(updated_at=self.clock(), **{k: v[1] for k, v in diff.items()})
        self.repo.save_item(updated)
        self.audit.record("item.updated", item.sku, changes=diff)
        return updated

    @_transactional
    def remove_item(self, sku):
        item = self.get(sku)
        if self.repo.open_orders_for(item.sku):
            raise ConflictError(f"{item.sku} has open orders; fulfil or cancel them first")
        self.repo.delete_item(item.sku)
        self.audit.record("item.removed", item.sku, name=item.name)
        return item

    # ---- stock movements ------------------------------------------------
    @_transactional
    def receive(self, sku, quantity, note=""):
        item = self.get(sku)
        check_quantity(quantity, "received quantity", allow_zero=False)
        new_qty = check_quantity(item.quantity + quantity, "resulting quantity")
        updated = item.with_changes(quantity=new_qty, updated_at=self.clock())
        self.repo.save_item(updated)
        self.audit.record("stock.received", item.sku, quantity=quantity,
                          new_quantity=new_qty, note=note or "")
        return updated

    @_transactional
    def adjust(self, sku, delta, reason):
        item = self.get(sku)
        if isinstance(delta, bool) or not isinstance(delta, int) or delta == 0:
            raise ValidationError("adjustment must be a non-zero integer")
        if not (reason or "").strip():
            raise ValidationError("an adjustment needs a reason")
        new_qty = item.quantity + delta
        if new_qty < 0:
            raise ValidationError(f"adjustment would make {item.sku} negative ({new_qty})")
        reserved = self.reserved(item.sku)
        if new_qty < reserved:
            raise ConflictError(
                f"adjustment would leave {new_qty} on hand but {reserved} are reserved"
            )
        check_quantity(new_qty, "resulting quantity")
        updated = item.with_changes(quantity=new_qty, updated_at=self.clock())
        self.repo.save_item(updated)
        self.audit.record("stock.adjusted", item.sku, delta=delta,
                          new_quantity=new_qty, reason=reason.strip())
        return updated

    # ---- orders -----------------------------------------------------------
    @_transactional
    def place_order(self, sku, quantity, customer=""):
        item = self.get(sku)
        check_quantity(quantity, "order quantity", allow_zero=False)
        customer = check_customer(customer)
        avail = item.quantity - self.reserved(item.sku)
        if quantity > avail:
            raise ConflictError(f"only {avail} of {item.sku} available, {quantity} requested")
        order = Order(id=self.repo.next_order_id(), sku=item.sku, quantity=quantity,
                      customer=customer, status=ORDER_OPEN, created_at=self.clock())
        self.repo.save_order(order)
        self.audit.record("order.placed", f"order:{order.id}", sku=item.sku,
                          quantity=quantity, customer=customer)
        return order

    def _open_order(self, order_id):
        order = self.order(order_id)
        if not order.is_open:
            raise ConflictError(f"order {order_id} is already {order.status}")
        return order

    @_transactional
    def fulfil_order(self, order_id):
        order = self._open_order(order_id)
        item = self.get(order.sku)
        if item.quantity < order.quantity:
            raise ConflictError(f"not enough {item.sku} on hand to fulfil order {order_id}")
        now = self.clock()
        new_qty = item.quantity - order.quantity
        self.repo.save_item(item.with_changes(quantity=new_qty, updated_at=now))
        closed = order.with_changes(status=ORDER_FULFILLED, closed_at=now)
        self.repo.save_order(closed)
        self.audit.record("order.fulfilled", f"order:{order.id}", sku=order.sku,
                          quantity=order.quantity, new_quantity=new_qty)
        return closed

    @_transactional
    def cancel_order(self, order_id, reason=""):
        order = self._open_order(order_id)
        closed = order.with_changes(status=ORDER_CANCELLED, closed_at=self.clock())
        self.repo.save_order(closed)
        self.audit.record("order.cancelled", f"order:{order.id}", sku=order.sku,
                          quantity=order.quantity, reason=(reason or "").strip())
        return closed

    # ---- bulk -------------------------------------------------------------
    @_transactional
    def import_items(self, rows):
        """Add many items at once from dicts with the ``add_item`` keys.

        All-or-nothing: if any row is invalid nothing is added, and the
        error message names the 1-based row number.
        """
        added = []
        for n, row in enumerate(rows, start=1):
            try:
                added.append(self._add_row(row))
            except (ValidationError, ConflictError) as exc:
                raise type(exc)(f"row {n}: {exc}") from None
        return added

    def _add_row(self, row):
        row = dict(row)
        unknown = set(row) - {"sku", "name", "quantity", "price_cents", "location", "reorder_level"}
        if unknown:
            raise ValidationError(f"unknown column(s): {', '.join(sorted(unknown))}")
        # call the undecorated body so the whole import is one transaction
        return InventoryService.add_item.__wrapped__(self, **row)
