import pytest

from meterbill.catalog import parse_catalog
from meterbill.errors import ConfigError, UnknownPlan

from .helpers import catalog


def test_catalog_loads():
    cat = catalog()
    assert [p.id for p in cat.plans()] == ["business", "business_eu", "legacy_basic", "starter", "team", "team_eu"]
    assert cat.plan("team_eu").currency == "EUR"
    assert cat.plan("legacy_basic").legacy
    assert cat.metrics.get("storage_gb").aggregation == "last"
    assert cat.plan("team").metrics() == ["api_calls", "storage_gb", "seats"]
    with pytest.raises(UnknownPlan):
        cat.plan("platinum")


def test_catalog_rejects_unknown_metric():
    text = '[metrics.a]\nname="A"\n[plans.p]\ncurrency="USD"\n[[plans.p.charges]]\nmetric="b"\nmodel="flat"\nunit_price="1"\n'
    with pytest.raises(ConfigError):
        parse_catalog(text)


def test_catalog_rejects_duplicate_charge():
    text = ('[metrics.a]\nname="A"\n[plans.p]\ncurrency="USD"\n'
            '[[plans.p.charges]]\nmetric="a"\nmodel="flat"\nunit_price="1"\n'
            '[[plans.p.charges]]\nmetric="a"\nmodel="flat"\nunit_price="2"\n')
    with pytest.raises(ConfigError):
        parse_catalog(text)


def test_catalog_requires_currency():
    with pytest.raises(ConfigError):
        parse_catalog('[metrics.a]\n[plans.p]\nbase_fee="1"\n')
