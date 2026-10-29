"""Tiny demo: ``python3 -m pricecache.cli`` prints a few quotes and the stats report."""

import json

from .server import PriceServer
from .service import PriceService


def demo_service() -> PriceService:
    svc = PriceService()
    svc.set_region("US", "USD", tax_bp=0)
    svc.set_region("DE", "EUR", tax_bp=1900, rounding="cent")
    svc.set_region("JP", "JPY", tax_bp=1000, rounding="whole")
    svc.set_fx("EUR", "0.92")
    svc.set_fx("JPY", "149.5")
    svc.set_price("MUG-01", 1299, tiers=[[10, 500], [50, 1200]])
    svc.set_price("TEE-02", 2499)
    svc.set_promo("FALL10", 1000, skus=["TEE-02"])
    return svc


def main() -> None:
    svc = demo_service()
    with PriceServer(svc, workers=4) as srv:
        for region in ("US", "DE", "JP"):
            q = srv.call("quote", sku="MUG-01", region=region, qty=12,
                         options={"gift_wrap": True})
            print(json.dumps(q, sort_keys=True))
        print(json.dumps(srv.call("stats"), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
