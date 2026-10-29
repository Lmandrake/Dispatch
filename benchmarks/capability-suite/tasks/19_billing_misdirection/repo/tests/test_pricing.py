from decimal import Decimal

import pytest

from meterbill.errors import ConfigError
from meterbill.pricing import fmt_qty, parse_price, rate

from .helpers import catalog

D = Decimal


def spec(**raw):
    return parse_price(raw, "test")


def test_per_unit_with_included():
    s = spec(model="per_unit", unit_price="0.0005", included=100000)
    assert rate(s, 99999).amount == 0
    r = rate(s, 250000)
    assert r.chargeable == 150000
    assert r.amount == D("75.00000000")


def test_graduated_splits_quantity():
    s = spec(model="graduated", tiers=[{"up_to": 1000, "unit_price": "0.10"},
                                       {"up_to": 5000, "unit_price": "0.05"},
                                       {"up_to": "inf", "unit_price": "0.01"}])
    r = rate(s, 7500)
    assert [sl.quantity for sl in r.slices] == [1000, 4000, 2500]
    assert r.amount == D("325.00000000")
    assert [sl.label for sl in r.slices] == ["1-1,000", "1,001-5,000", "above 5,000"]


def test_graduated_flat_fee_once_per_touched_tier():
    s = spec(model="graduated", tiers=[{"up_to": 10, "unit_price": "1", "flat_fee": "5"},
                                       {"up_to": "inf", "unit_price": "0.5", "flat_fee": "2"}])
    assert rate(s, 4).amount == D("9")
    assert rate(s, 14).amount == D("19")


def test_volume_prices_whole_quantity_in_one_tier():
    s = spec(model="volume", tiers=[{"up_to": 100, "unit_price": "2.00"},
                                    {"up_to": 1000, "unit_price": "1.50"},
                                    {"up_to": "inf", "unit_price": "1.00"}])
    assert rate(s, 40).amount == D("80")
    assert rate(s, 400).amount == D("600")
    assert rate(s, 4000).amount == D("4000")
    assert rate(s, 0).amount == 0


def test_package_rounds_blocks_up():
    s = spec(model="package", package_size=100, unit_price="1.90", included=200)
    assert rate(s, 200).amount == 0
    assert rate(s, D("200.001")).amount == D("1.90")
    assert rate(s, 501).amount == D("7.60")


def test_flat():
    s = spec(model="flat", unit_price="15")
    assert rate(s, 0).amount == D(15)
    assert rate(s, 999).amount == D(15)


@pytest.mark.parametrize("raw", [
    {"model": "magic", "unit_price": "1"},
    {"model": "per_unit"},
    {"model": "graduated", "tiers": []},
    {"model": "graduated", "tiers": [{"up_to": 10, "unit_price": "1"}]},
    {"model": "volume", "tiers": [{"up_to": 10, "unit_price": "1"}, {"up_to": 5, "unit_price": "1"},
                                  {"up_to": "inf", "unit_price": "1"}]},
    {"model": "package", "unit_price": "1", "package_size": 0},
    {"model": "per_unit", "unit_price": "-1"},
])
def test_bad_price_specs(raw):
    with pytest.raises(ConfigError):
        parse_price(raw, "test")


def test_negative_quantity_rejected():
    with pytest.raises(ValueError):
        rate(spec(model="per_unit", unit_price="1"), -1)


def test_catalog_team_api_calls():
    team = catalog().plan("team")
    r = team.rate("api_calls", 2500000)
    assert r.amount == D("775.00000000")
    assert team.rate("seats", 7).amount == D("84.00000000")
    assert team.rate("seats", 18).amount == D("180.00000000")
    assert team.rate("nothing", 1) is None


def test_fmt_qty():
    assert fmt_qty(1000000) == "1,000,000"
    assert fmt_qty(D("2.50")) == "2.5"
