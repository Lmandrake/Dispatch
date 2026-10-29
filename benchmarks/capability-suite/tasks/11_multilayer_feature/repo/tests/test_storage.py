import json

import pytest

from stockroom.errors import StorageError
from stockroom.models import AuditEvent, Item, Order
from stockroom.storage import JsonFileRepository, MemoryRepository, open_repository
from stockroom.storage.jsonfile import FORMAT_VERSION


@pytest.fixture(params=["memory", "json"])
def repo(request, tmp_path):
    if request.param == "memory":
        return MemoryRepository()
    return JsonFileRepository(tmp_path / "db.json")


def test_items_roundtrip_sorted(repo):
    repo.save_item(Item("B-001", "b"))
    repo.save_item(Item("A-001", "a", location="X1"))
    assert [i.sku for i in repo.list_items()] == ["A-001", "B-001"]
    assert repo.get_item("A-001").location == "X1"
    assert repo.delete_item("A-001") is True
    assert repo.delete_item("A-001") is False


def test_location_index_follows_updates(repo):
    repo.save_item(Item("A-001", "a", location="X1"))
    repo.save_item(Item("A-001", "a", location="X2"))
    assert repo.items_at("X1") == []
    assert [i.sku for i in repo.items_at("X2")] == ["A-001"]


def test_orders_and_ids(repo):
    assert repo.next_order_id() == 1
    repo.save_order(Order(1, "A-001", 3))
    assert repo.next_order_id() == 2
    assert repo.get_order(1).quantity == 3


def test_rollback(repo):
    repo.save_item(Item("A-001", "a"))
    repo.commit()
    repo.save_item(Item("B-001", "b", location="Z"))
    repo.append_event(AuditEvent(1, "t", "x", "y"))
    repo.rollback()
    assert [i.sku for i in repo.list_items()] == ["A-001"]
    assert repo.items_at("Z") == []
    assert repo.list_events() == []


def test_json_persists_only_on_commit(tmp_path):
    path = tmp_path / "db.json"
    r = JsonFileRepository(path)
    r.save_item(Item("A-001", "a", quantity=2))
    assert not path.exists()
    r.commit()
    doc = json.loads(path.read_text())
    assert doc["version"] == FORMAT_VERSION
    r2 = JsonFileRepository(path)
    assert r2.get_item("A-001").quantity == 2


def test_json_v1_migration(tmp_path):
    path = tmp_path / "old.json"
    path.write_text(json.dumps({
        "version": 1,
        "items": [{"sku": "A-001", "name": "a", "quantity": 1, "price_cents": 5, "bin": "S3"}],
        "orders": [{"id": 7, "sku": "A-001", "quantity": 1}],
        "events": [],
    }))
    r = JsonFileRepository(path)
    assert r.get_item("A-001").location == "S3"
    assert r.next_order_id() == 8


def test_json_refuses_future_version(tmp_path):
    path = tmp_path / "f.json"
    path.write_text(json.dumps({"version": FORMAT_VERSION + 1, "items": []}))
    with pytest.raises(StorageError):
        JsonFileRepository(path)


def test_json_bad_file(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{nope")
    with pytest.raises(StorageError):
        JsonFileRepository(path)


def test_open_repository():
    assert isinstance(open_repository(":memory:"), MemoryRepository)
