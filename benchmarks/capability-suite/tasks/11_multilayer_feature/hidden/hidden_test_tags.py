import csv
import io
import json

import pytest

from stockroom.cli import main
from stockroom.clock import FixedClock
from stockroom.errors import QueryError, StorageError, ValidationError
from stockroom.export import (
    export_items,
    items_to_csv,
    items_to_json,
    items_to_table,
    orders_to_csv,
    orders_to_json,
    parse_items_csv,
)
from stockroom.models import Item, Order
from stockroom.query import filter_items
from stockroom.services import InventoryService
from stockroom.storage import JsonFileRepository, MemoryRepository


# ---- helpers -------------------------------------------------------------

def svc_with(repo=None):
    clock = FixedClock("2026-05-01T09:00:00Z")
    return InventoryService(repo if repo is not None else MemoryRepository(), clock=clock), clock


def run(db, *argv):
    out, err = io.StringIO(), io.StringIO()
    rc = main(["--db", str(db), *argv], out=out, err=err)
    return rc, out.getvalue(), err.getvalue()


@pytest.fixture(params=["memory", "json"])
def repo(request, tmp_path):
    if request.param == "memory":
        return MemoryRepository()
    return JsonFileRepository(tmp_path / "db.json")


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKROOM_NOW", "2026-05-01T09:00:00Z")
    path = tmp_path / "stock.json"
    assert run(path, "add", "BOLT-0042", "Hex bolt M6", "--qty", "120", "--price", "0.15",
               "--location", "A1", "--reorder", "50", "--tag", "Fastener", "--tag", "metric")[0] == 0
    assert run(path, "add", "SAW-010", "Hand saw", "--qty", "3", "--price", "24.99",
               "--tag", "tools", "--tag", "fragile")[0] == 0
    assert run(path, "add", "TAPE-100", "Duct tape", "--qty", "7", "--price", "6.50",
               "--location", "B2")[0] == 0
    return path


def _tagged():
    return [
        Item("BOLT-001", "Hex bolt", quantity=10, price_cents=15, location="A1", tags=("fastener", "metric")),
        Item("NUT-001", "Hex nut", quantity=40, price_cents=5, location="A2", tags=("fastener",)),
        Item("SAW-010", "Hand saw", quantity=3, price_cents=2499, tags=("fragile", "q3-audit", "tools")),
        Item("TAPE-100", "Duct tape", quantity=0, price_cents=650),
    ]


class _Lazy:
    def __iter__(self):
        return iter(_tagged())


TAGGED = _Lazy()


def skus(q):
    return [i.sku for i in filter_items(TAGGED, q)]


# ---- model / validation / service ----------------------------------------

def test_item_default_tags():
    assert Item("AA-001", "x").tags == ()


def test_add_item_normalises_tags_and_event():
    s, _ = svc_with()
    item = s.add_item("AA-001", "thing", tags=[" Zeta ", "alpha", "ALPHA", "b_2-x"])
    assert item.tags == ("alpha", "b_2-x", "zeta")
    assert s.get("AA-001").tags == ("alpha", "b_2-x", "zeta")
    ev = s.audit.events()[-1]
    assert ev.action == "item.added"
    assert ev.details["tags"] == ["alpha", "b_2-x", "zeta"]


def test_add_item_without_tags_event_unchanged():
    s, _ = svc_with()
    s.add_item("AA-001", "thing", quantity=2, price_cents=5, location="X")
    assert s.audit.events()[-1].details == {"name": "thing", "quantity": 2, "price_cents": 5, "location": "X"}


@pytest.mark.parametrize("bad", ["", "  ", "-lead", "has space", "a" * 25, "semi;colon", "ünï", "a,b", "_x"])
def test_invalid_tags_rejected(bad):
    s, _ = svc_with()
    with pytest.raises(ValidationError):
        s.add_item("AA-001", "thing", tags=[bad])
    assert s.repo.list_items() == []
    assert s.audit.events() == []


def test_tag_length_boundary():
    s, _ = svc_with()
    assert s.add_item("AA-001", "thing", tags=["a" * 24]).tags == ("a" * 24,)


def test_max_ten_tags():
    s, _ = svc_with()
    s.add_item("AA-001", "thing", tags=[f"t{i}" for i in range(10)])
    with pytest.raises(ValidationError):
        s.add_item("BB-001", "thing", tags=[f"t{i}" for i in range(11)])
    with pytest.raises(ValidationError):
        s.tag_item("AA-001", "eleven")
    assert len(s.get("AA-001").tags) == 10
    assert [e.action for e in s.audit.events()] == ["item.added"]


def test_tag_item_records_only_new_tags():
    s, clock = svc_with()
    s.add_item("AA-001", "thing", tags=["red"])
    clock.advance(60)
    item = s.tag_item("aa-001", "Blue", "red", "green", "blue")
    assert item.tags == ("blue", "green", "red")
    assert item.updated_at == "2026-05-01T09:01:00Z"
    ev = s.audit.events()[-1]
    assert (ev.action, ev.subject, ev.details) == ("item.tagged", "AA-001", {"tags": ["blue", "green"]})


def test_tag_item_noop():
    s, clock = svc_with()
    s.add_item("AA-001", "thing", tags=["red"])
    clock.advance(60)
    item = s.tag_item("AA-001", "RED")
    assert item.tags == ("red",)
    assert item.updated_at == "2026-05-01T09:00:00Z"
    assert len(s.audit.events()) == 1


def test_tag_item_invalid_changes_nothing():
    s, _ = svc_with()
    s.add_item("AA-001", "thing", tags=["red"])
    with pytest.raises(ValidationError):
        s.tag_item("AA-001", "ok", "not ok")
    assert s.get("AA-001").tags == ("red",)
    assert len(s.audit.events()) == 1


def test_untag_item():
    s, clock = svc_with()
    s.add_item("AA-001", "thing", tags=["red", "blue", "green"])
    clock.advance(5)
    item = s.untag_item("AA-001", "GREEN", "purple", "red")
    assert item.tags == ("blue",)
    ev = s.audit.events()[-1]
    assert (ev.action, ev.subject, ev.details) == ("item.untagged", "AA-001", {"tags": ["green", "red"]})
    n = len(s.audit.events())
    assert s.untag_item("AA-001", "purple").tags == ("blue",)
    assert len(s.audit.events()) == n
    assert s.get("AA-001").updated_at == "2026-05-01T09:00:05Z"


def test_update_item_does_not_accept_tags():
    s, _ = svc_with()
    s.add_item("AA-001", "thing")
    with pytest.raises(ValidationError):
        s.update_item("AA-001", tags=("x",))


def test_update_keeps_tags():
    s, _ = svc_with()
    s.add_item("AA-001", "thing", tags=["red"])
    s.update_item("AA-001", price_cents=99)
    assert s.get("AA-001").tags == ("red",)


def test_import_rows_with_tags_all_or_nothing():
    s, _ = svc_with()
    s.import_items([{"sku": "AA-001", "name": "a", "tags": ["X", "y"]}, {"sku": "BB-001", "name": "b"}])
    assert s.get("AA-001").tags == ("x", "y") and s.get("BB-001").tags == ()
    with pytest.raises(ValidationError, match="row 2"):
        s.import_items([{"sku": "CC-001", "name": "c"}, {"sku": "DD-001", "name": "d", "tags": ["bad tag"]}])
    assert [i.sku for i in s.repo.list_items()] == ["AA-001", "BB-001"]


# ---- storage --------------------------------------------------------------

def test_items_with_tag_index(repo):
    repo.save_item(Item("BB-001", "b", tags=("red",)))
    repo.save_item(Item("AA-001", "a", tags=("blue", "red")))
    assert [i.sku for i in repo.items_with_tag("red")] == ["AA-001", "BB-001"]
    repo.save_item(Item("AA-001", "a", tags=("blue",)))
    assert [i.sku for i in repo.items_with_tag("red")] == ["BB-001"]
    assert [i.sku for i in repo.items_with_tag("blue")] == ["AA-001"]
    repo.delete_item("BB-001")
    assert repo.items_with_tag("red") == []
    assert repo.items_with_tag("nothing") == []


def test_items_with_tag_survives_rollback(repo):
    repo.save_item(Item("AA-001", "a", tags=("red",)))
    repo.commit()
    repo.save_item(Item("AA-001", "a", tags=("green",)))
    repo.save_item(Item("BB-001", "b", tags=("red",)))
    repo.rollback()
    assert [i.sku for i in repo.items_with_tag("red")] == ["AA-001"]
    assert repo.items_with_tag("green") == []
    assert repo.get_item("AA-001").tags == ("red",)


def test_service_rollback_restores_tag_index():
    s, _ = svc_with()
    s.add_item("AA-001", "thing", quantity=1, tags=["red"])
    with pytest.raises(ValidationError):
        s.import_items([{"sku": "BB-001", "name": "b", "tags": ["red"]}, {"sku": "bad", "name": "c"}])
    assert [i.sku for i in s.repo.items_with_tag("red")] == ["AA-001"]


def test_json_writes_v3_with_tags(tmp_path):
    path = tmp_path / "db.json"
    r = JsonFileRepository(path)
    r.save_item(Item("AA-001", "a", tags=("blue", "red")))
    r.save_item(Item("BB-001", "b"))
    r.commit()
    doc = json.loads(path.read_text())
    assert doc["version"] == 3
    assert doc["items"][0]["tags"] == ["blue", "red"]
    assert doc["items"][1]["tags"] == []
    r2 = JsonFileRepository(path)
    assert r2.get_item("AA-001").tags == ("blue", "red")
    assert isinstance(r2.get_item("AA-001").tags, tuple)
    assert [i.sku for i in r2.items_with_tag("blue")] == ["AA-001"]


V2_DOC = {
    "version": 2,
    "next_order_id": 3,
    "items": [
        {"sku": "AA-001", "name": "a", "quantity": 5, "price_cents": 100, "location": "S1",
         "reorder_level": 0, "created_at": "t0", "updated_at": "t0"},
    ],
    "orders": [{"id": 2, "sku": "AA-001", "quantity": 1, "customer": "", "status": "open",
                "created_at": "t0", "closed_at": ""}],
    "events": [{"seq": 1, "timestamp": "t0", "action": "item.added", "subject": "AA-001",
                "details": {"name": "a"}}],
}


def test_v2_file_loads_and_upgrades(tmp_path):
    path = tmp_path / "v2.json"
    path.write_text(json.dumps(V2_DOC))
    s = InventoryService(JsonFileRepository(path), clock=FixedClock())
    assert s.get("AA-001").tags == ()
    assert s.available("AA-001") == 4
    s.tag_item("AA-001", "old")
    doc = json.loads(path.read_text())
    assert doc["version"] == 3
    assert doc["items"][0]["tags"] == ["old"]
    assert doc["next_order_id"] == 3
    assert [e["action"] for e in doc["events"]] == ["item.added", "item.tagged"]
    assert [e["seq"] for e in doc["events"]] == [1, 2]


def test_v1_file_still_loads(tmp_path):
    path = tmp_path / "v1.json"
    path.write_text(json.dumps({
        "version": 1,
        "items": [{"sku": "AA-001", "name": "a", "quantity": 1, "price_cents": 5, "bin": "S3"}],
        "orders": [{"id": 7, "sku": "AA-001", "quantity": 1}],
        "events": [],
    }))
    r = JsonFileRepository(path)
    item = r.get_item("AA-001")
    assert (item.location, item.tags) == ("S3", ())
    assert r.next_order_id() == 8
    r.commit()
    doc = json.loads(path.read_text())
    assert doc["version"] == 3 and doc["items"][0]["tags"] == []
    assert "bin" not in doc["items"][0]


def test_future_version_refused(tmp_path):
    path = tmp_path / "v4.json"
    path.write_text(json.dumps({"version": 4, "items": []}))
    with pytest.raises(StorageError):
        JsonFileRepository(path)


# ---- query language ----------------------------------------------------------

@pytest.mark.parametrize("q,expected", [
    ("tag = fastener", ["BOLT-001", "NUT-001"]),
    ("tag = FRAGILE", ["SAW-010"]),
    ("tags = metric", ["BOLT-001"]),
    ("tag != fastener", ["SAW-010", "TAPE-100"]),
    ("tag in (metric, tools)", ["BOLT-001", "SAW-010"]),
    ("tag in (nothing)", []),
    ("tag ~ AUD", ["SAW-010"]),
    ("tag ~ t", ["BOLT-001", "NUT-001", "SAW-010"]),
    ("tagged", ["BOLT-001", "NUT-001", "SAW-010"]),
    ("not tagged", ["TAPE-100"]),
    ("tagged = false", ["TAPE-100"]),
    ("tag = 'q3-audit'", ["SAW-010"]),
    ("tag = fastener and qty > 20", ["NUT-001"]),
    ("tag = fastener or price > 6", ["BOLT-001", "NUT-001", "SAW-010", "TAPE-100"]),
    ("not (tag = fastener) and tagged", ["SAW-010"]),
    ("loc ~ a tag = metric", ["BOLT-001"]),
])
def test_tag_queries(q, expected):
    assert skus(q) == expected


@pytest.mark.parametrize("bad", ["tag < x", "tag >= x", "tag", "tagged ~ x", "tag in ()", "tag ="])
def test_tag_query_errors(bad):
    with pytest.raises(QueryError):
        filter_items(TAGGED, bad)


def test_existing_queries_unchanged():
    assert skus("qty < 5") == ["SAW-010", "TAPE-100"]
    assert skus("name ~ hex and price = 0.05") == ["NUT-001"]
    with pytest.raises(QueryError) as exc:
        filter_items(TAGGED, "qty < 5 and colour = red")
    assert exc.value.position == 12


# ---- exports / import ------------------------------------------------------------

def test_csv_export_tags_column():
    lines = items_to_csv(TAGGED).splitlines()
    assert lines[0] == "sku,name,quantity,price,location,reorder_level,value,tags"
    assert lines[1] == "BOLT-001,Hex bolt,10,0.15,A1,0,1.50,fastener;metric"
    assert lines[3] == "SAW-010,Hand saw,3,24.99,,0,74.97,fragile;q3-audit;tools"
    assert lines[4] == "TAPE-100,Duct tape,0,6.50,,0,0.00,"


def test_json_export_tags_key():
    data = json.loads(items_to_json(TAGGED))
    assert list(data[0]) == ["sku", "name", "quantity", "price", "price_cents", "location",
                             "reorder_level", "value_cents", "tags"]
    assert data[0]["tags"] == ["fastener", "metric"]
    assert data[3]["tags"] == []


def test_table_export_tags_column():
    assert items_to_table(TAGGED) == (
        "SKU       Name       Qty  Price  Location  Tags                    Value\n"
        "--------  ---------  ---  -----  --------  ----------------------  -----\n"
        "BOLT-001  Hex bolt    10   0.15  A1        fastener,metric          1.50\n"
        "NUT-001   Hex nut     40   0.05  A2        fastener                 2.00\n"
        "SAW-010   Hand saw     3  24.99  -         fragile,q3-audit,tools  74.97\n"
        "TAPE-100  Duct tape    0   6.50  -         -                        0.00\n"
        "\n"
        "4 items, 53 units, total value 78.47\n"
    )
    assert export_items(TAGGED, "table") == items_to_table(TAGGED)


def test_csv_import_roundtrip_with_tags():
    rows = parse_items_csv(items_to_csv(TAGGED))
    s, _ = svc_with()
    s.import_items(rows)
    assert [i.tags for i in s.repo.list_items()] == [i.tags for i in TAGGED]
    rows = parse_items_csv("sku,name,tags\nAA-001,a, Red ; blue \nBB-001,b,\n")
    s2, _ = svc_with()
    s2.import_items(rows)
    assert s2.get("AA-001").tags == ("blue", "red")
    assert s2.get("BB-001").tags == ()


def test_csv_import_old_header_still_works():
    rows = parse_items_csv("sku,name,quantity,price,location,reorder_level,value\nAA-001,a,1,2.00,X,0,2.00\n")
    s, _ = svc_with()
    s.import_items(rows)
    item = s.get("AA-001")
    assert (item.quantity, item.price_cents, item.location, item.tags) == (1, 200, "X", ())
    with pytest.raises(ValidationError):
        parse_items_csv("sku,name,colour\nAA-001,a,red\n")


def test_order_exports_unchanged():
    orders = [Order(1, "A-001", 2, customer="Bob", status="open", created_at="t1")]
    assert orders_to_csv(orders) == "id,sku,quantity,customer,status,created_at,closed_at\n1,A-001,2,Bob,open,t1,\n"
    assert list(json.loads(orders_to_json(orders))[0]) == ["id", "sku", "quantity", "customer", "status",
                                                          "created_at", "closed_at"]


# ---- CLI ----------------------------------------------------------------------------

def test_cli_tag_and_untag(db):
    assert run(db, "tag", "saw-010", "Q3-Audit", "tools") == (0, "SAW-010: tags fragile, q3-audit, tools\n", "")
    assert run(db, "untag", "SAW-010", "fragile", "nope") == (0, "SAW-010: tags q3-audit, tools\n", "")
    assert run(db, "untag", "SAW-010", "q3-audit", "tools") == (0, "SAW-010: no tags\n", "")
    assert run(db, "tag", "TAPE-100", "x1")[1] == "TAPE-100: tags x1\n"
    rc, out, err = run(db, "tag", "TAPE-100", "bad tag")
    assert rc == 1 and err.startswith("error: ") and out == ""
    rc, _, err = run(db, "tag", "NOPE-001", "x")
    assert rc == 1 and err.startswith("error: ")


def test_cli_add_tags_persisted_and_history(db):
    doc = json.loads(db.read_text())
    assert doc["version"] == 3
    assert doc["items"][0]["tags"] == ["fastener", "metric"]
    run(db, "tag", "TAPE-100", "sticky")
    rc, out, _ = run(db, "history", "--json")
    events = [json.loads(l) for l in out.splitlines()]
    assert events[0]["details"]["tags"] == ["fastener", "metric"]
    assert "tags" not in events[2]["details"]
    assert events[3] == {"seq": 4, "timestamp": "2026-05-01T09:00:00Z", "action": "item.tagged",
                         "subject": "TAPE-100", "details": {"tags": ["sticky"]}}
    rc, out, _ = run(db, "history", "--action", "item.tagged")
    assert out == "#4 2026-05-01T09:00:00Z item.tagged TAPE-100 tags=['sticky']\n"


def test_cli_list_tag_filters(db):
    rc, out, _ = run(db, "list", "--tag", "metric", "--format", "csv")
    assert [l.split(",")[0] for l in out.splitlines()[1:]] == ["BOLT-0042"]
    rc, out, _ = run(db, "list", "--tag", "metric", "--tag", "tools", "--format", "csv")
    assert out.splitlines()[1:] == []
    rc, out, _ = run(db, "list", "--tag", "TOOLS", "--tag", "fragile", "--format", "csv")
    assert [l.split(",")[0] for l in out.splitlines()[1:]] == ["SAW-010"]
    rc, out, _ = run(db, "list", "--tag", "fastener", "--where", "qty < 10", "--format", "csv")
    assert out.splitlines()[1:] == []
    rc, out, _ = run(db, "list", "--tag", "fastener", "--low", "--location", "A1", "--format", "json")
    assert json.loads(out) == []
    run(db, "adjust", "BOLT-0042", "-80", "--reason", "count")
    rc, out, _ = run(db, "list", "--tag", "fastener", "--low", "--location", "A1", "--format", "json")
    assert [d["sku"] for d in json.loads(out)] == ["BOLT-0042"]
    rc, out, _ = run(db, "list", "--where", "not tagged", "--format", "csv")
    assert out.splitlines() == ["sku,name,quantity,price,location,reorder_level,value,tags",
                                "TAPE-100,Duct tape,7,6.50,B2,0,45.50,"]


def test_cli_show_tags_line(db):
    rc, out, _ = run(db, "show", "BOLT-0042")
    lines = out.splitlines()
    i = lines.index("Location:   A1")
    assert lines[i + 1] == "Tags:       fastener, metric"
    assert lines[i + 2] == "Reorder at: 50"
    assert lines[0] == "SKU:        BOLT-0042" and len(lines) == 12
    rc, out, _ = run(db, "show", "TAPE-100")
    assert "Location:   B2\nTags:       -\nReorder at: 0\n" in out


def test_cli_report_tags(db):
    rc, out, _ = run(db, "report", "tags")
    assert rc == 0
    assert out == (
        "Tag         Items  Units\n"
        "----------  -----  -----\n"
        "fastener        1    120\n"
        "fragile         1      3\n"
        "metric          1    120\n"
        "tools           1      3\n"
        "(untagged)      1      7\n"
    )
    run(db, "tag", "TAPE-100", "tools")
    rc, out, _ = run(db, "report", "tags")
    assert out.splitlines()[-1] == "tools         2     10"
    assert "(untagged)" not in out


def test_cli_export_import_roundtrip(db, tmp_path):
    f = tmp_path / "items.csv"
    assert run(db, "export", "items", "-o", str(f))[0] == 0
    assert f.read_text().splitlines()[1] == "BOLT-0042,Hex bolt M6,120,0.15,A1,50,18.00,fastener;metric"
    other = tmp_path / "other.json"
    assert run(other, "import", str(f)) == (0, "imported 3 items\n", "")
    rc, out, _ = run(other, "export", "items", "--format", "json", "--where", "tag = fragile")
    assert [(d["sku"], d["tags"]) for d in json.loads(out)] == [("SAW-010", ["fragile", "tools"])]


def test_cli_existing_commands_unchanged(db):
    assert run(db, "order", "place", "BOLT-0042", "30", "--customer", "Line 3")[1] == "order 1 placed: 30 x BOLT-0042\n"
    assert run(db, "order", "fulfil", "1")[1] == "order 1 fulfilled\n"
    rc, out, _ = run(db, "report")
    assert out == ("Items:        3\nUnits:        100\nStock value:  133.97\n"
                   "Open orders:  0 (0 units reserved)\nLow stock:    0\n")
    rc, out, _ = run(db, "report", "locations")
    assert out.splitlines()[-1].split() == ["-", "1", "3", "74.97"]
    assert run(db, "update", "SAW-010", "--price", "24.99")[1] == "SAW-010 unchanged\n"
    rc, out, _ = run(db, "history", "--sku", "tape-100")
    assert out == ("#3 2026-05-01T09:00:00Z item.added TAPE-100 location='B2' name='Duct tape' "
                   "price_cents=650 quantity=7\n")
    rc, _, err = run(db, "list", "--where", "qty <")
    assert rc == 1 and "expected a value" in err
