import pytest

from stockroom.errors import ConflictError, NotFoundError, ValidationError
from tests.helpers import make_service


@pytest.fixture
def svc():
    s, _ = make_service()
    s.add_item("bolt-0042", "Hex bolt", quantity=10, price_cents=15, location="A1", reorder_level=3)
    return s


def test_add_normalises_and_audits(svc):
    item = svc.get("BOLT-0042")
    assert item.sku == "BOLT-0042"
    ev = svc.audit.events()[-1]
    assert (ev.seq, ev.action, ev.subject) == (1, "item.added", "BOLT-0042")
    assert ev.details["location"] == "A1"


def test_add_rejects_duplicates_and_bad_input(svc):
    with pytest.raises(ConflictError):
        svc.add_item("BOLT-0042", "again")
    with pytest.raises(ValidationError):
        svc.add_item("bad sku", "x")
    with pytest.raises(ValidationError):
        svc.add_item("NUT-001", "  ")
    with pytest.raises(ValidationError):
        svc.add_item("NUT-001", "nut", quantity=-1)
    assert len(svc.audit.events()) == 1


def test_update_records_diff_only(svc):
    svc.update_item("BOLT-0042", name="Hex bolt", price_cents=20)
    ev = svc.audit.events()[-1]
    assert ev.action == "item.updated"
    assert ev.details == {"changes": {"price_cents": [15, 20]}}
    n = len(svc.audit.events())
    svc.update_item("BOLT-0042", price_cents=20)
    assert len(svc.audit.events()) == n


def test_update_unknown_field(svc):
    with pytest.raises(ValidationError):
        svc.update_item("BOLT-0042", quantity=5)


def test_receive_and_adjust(svc):
    assert svc.receive("BOLT-0042", 5).quantity == 15
    assert svc.adjust("BOLT-0042", -2, "count").quantity == 13
    with pytest.raises(ValidationError):
        svc.adjust("BOLT-0042", -100, "oops")
    with pytest.raises(ValidationError):
        svc.adjust("BOLT-0042", 1, " ")


def test_orders_reserve_and_fulfil(svc):
    o = svc.place_order("BOLT-0042", 4, customer="Line 3")
    assert svc.available("BOLT-0042") == 6
    with pytest.raises(ConflictError):
        svc.place_order("BOLT-0042", 7)
    with pytest.raises(ConflictError):
        svc.adjust("BOLT-0042", -7, "shrink")
    svc.fulfil_order(o.id)
    assert svc.get("BOLT-0042").quantity == 6
    assert svc.available("BOLT-0042") == 6
    with pytest.raises(ConflictError):
        svc.cancel_order(o.id)


def test_cancel_releases(svc):
    o = svc.place_order("BOLT-0042", 10)
    svc.cancel_order(o.id, reason="dup")
    assert svc.available("BOLT-0042") == 10
    assert svc.orders(status="cancelled")[0].id == o.id


def test_remove_blocked_by_open_order(svc):
    o = svc.place_order("BOLT-0042", 1)
    with pytest.raises(ConflictError):
        svc.remove_item("BOLT-0042")
    svc.cancel_order(o.id)
    svc.remove_item("BOLT-0042")
    with pytest.raises(NotFoundError):
        svc.get("BOLT-0042")


def test_low_stock(svc):
    assert svc.low_stock() == []
    svc.adjust("BOLT-0042", -7, "count")
    assert [i.sku for i in svc.low_stock()] == ["BOLT-0042"]


def test_import_is_all_or_nothing(svc):
    rows = [{"sku": "NUT-001", "name": "Nut"}, {"sku": "BOLT-0042", "name": "dup"}]
    with pytest.raises(ConflictError, match="row 2"):
        svc.import_items(rows)
    with pytest.raises(NotFoundError):
        svc.get("NUT-001")
    added = svc.import_items([{"sku": "NUT-001", "name": "Nut"}, {"sku": "WASH-001", "name": "Washer"}])
    assert [i.sku for i in added] == ["NUT-001", "WASH-001"]


def test_failed_operation_leaves_no_event(svc):
    n = len(svc.audit.events())
    with pytest.raises(ConflictError):
        svc.place_order("BOLT-0042", 99)
    assert len(svc.audit.events()) == n
