"""PriceService: quotes computed from store records, behind two caches.

* the record cache holds store Records by store key (("price", sku), ...),
  ttl ``record_ttl`` (default 30 s);
* the quote cache holds computed Quotes by QuoteKey, ttl ``quote_ttl``
  (default 300 s), because computing a quote reads up to four records.

Every write goes through the store, which notifies ``_on_write``; that drops
the affected record-cache entry and every quote that could depend on it, so a
write is visible to the very next quote() call regardless of TTLs. TTLs only
bound how long an entry lives when nothing changes.
"""

from typing import Optional

from . import keys as K
from .cache import ReadThroughCache
from .clock import resolve
from .pricing import BASE_CURRENCY, compute_quote
from .stats import Stats
from .store import VersionedStore


class NotFound(KeyError):
    pass


class PriceService:
    def __init__(
        self,
        store: Optional[VersionedStore] = None,
        clock=None,
        stats: Optional[Stats] = None,
        quote_ttl: Optional[float] = 300.0,
        record_ttl: Optional[float] = 30.0,
        quote_maxsize: int = 10_000,
        record_maxsize: int = 4_096,
        warm_on_write: bool = True,
    ):
        self.clock = resolve(clock)
        self.store = store if store is not None else VersionedStore(clock=self.clock)
        self.stats = stats if stats is not None else Stats(clock=self.clock)
        self.records = ReadThroughCache(
            "records", ttl=record_ttl, maxsize=record_maxsize, clock=self.clock, stats=self.stats
        )
        self.quotes = ReadThroughCache(
            "quotes", ttl=quote_ttl, maxsize=quote_maxsize, clock=self.clock, stats=self.stats
        )
        self.warm_on_write = warm_on_write
        self._unsubscribe = self.store.subscribe(self._on_write)

    def close(self) -> None:
        self._unsubscribe()

    # ------------------------------------------------------------------ reads

    def record(self, kind: str, name: str):
        """The current Record for (kind, name) through the record cache, or None."""
        key = K.record_key(kind, name)
        return self.records.get(key, self.store.get)

    def quote(self, sku: str, region: str, qty: int = 1, channel: str = "web", options=None):
        """Price ``qty`` units of ``sku`` for ``region`` / ``channel`` with ``options``."""
        self.stats.incr("service.quote_calls")
        qkey = K.quote_key(sku, region, qty, channel, options)
        opts = dict(options or {})

        def load(_key):
            return self._compute(qkey.sku, qkey.region, qkey.qty, qkey.channel, opts)

        return self.quotes.get(qkey, load)

    def _compute(self, sku, region, qty, channel, options):
        price = self.record("price", sku)
        region_rec = self.record("region", region)
        fx = None
        if region_rec is not None and not region_rec.deleted:
            currency = region_rec.value.get("currency", BASE_CURRENCY)
            if currency != BASE_CURRENCY:
                fx = self.record("fx", currency)
        promo = None
        if options.get("promo"):
            promo = self.record("promo", str(options["promo"]))
        return compute_quote(sku, region, qty, channel, options, price, region_rec, fx, promo)

    # ----------------------------------------------------------------- writes

    def set_price(self, sku: str, base_cents: int, tiers=None):
        value = {"base_cents": int(base_cents), "currency": BASE_CURRENCY,
                 "tiers": [list(t) for t in (tiers or [])]}
        return self._write(K.record_key("price", sku), value)

    def set_region(self, code: str, currency: str = BASE_CURRENCY, tax_bp: int = 0,
                   markup_bp: int = 0, rounding: str = "cent"):
        value = {"currency": currency.upper(), "tax_bp": int(tax_bp),
                 "markup_bp": int(markup_bp), "rounding": rounding}
        return self._write(K.record_key("region", code), value)

    def set_fx(self, currency: str, rate):
        return self._write(K.record_key("fx", currency), {"rate": str(rate)})

    def set_promo(self, code: str, discount_bp: int, skus="*", active: bool = True,
                  min_qty: int = 1):
        value = {"discount_bp": int(discount_bp),
                 "skus": skus if skus == "*" else list(skus),
                 "active": bool(active), "min_qty": int(min_qty)}
        return self._write(K.record_key("promo", code), value)

    def delete_price(self, sku: str):
        rec = self.store.delete(K.record_key("price", sku))
        if rec is None:
            raise NotFound(sku)
        return rec

    def _write(self, key, value):
        rec = self.store.put(key, value)
        if self.warm_on_write:
            # The listener already dropped the stale entry; put the new record
            # in so the next quote does not have to go to the store for it.
            self.records.put(key, rec)
        return rec

    # ---------------------------------------------------------- invalidation

    def _regions_using(self, currency: str) -> set:
        out = set()
        for key in self.store.keys("region"):
            hist = self.store.history(key)
            if hist and hist[-1].value.get("currency", BASE_CURRENCY) == currency:
                out.add(key[1])
        return out

    def _on_write(self, rec) -> None:
        kind, name = rec.key
        self.records.invalidate(rec.key)
        if kind == "price":
            self.quotes.invalidate_where(lambda q: q.sku == name)
        elif kind == "region":
            self.quotes.invalidate_where(lambda q: q.region == name)
        elif kind == "fx":
            regions = self._regions_using(name)
            self.quotes.invalidate_where(lambda q: q.region in regions)
        else:
            # Promotions change rarely and can touch any quote.
            self.quotes.clear()
        self.stats.incr(f"service.writes.{kind}")

    # ----------------------------------------------------------------- stats

    def stats_report(self) -> dict:
        """Hit ratios and sizes for the dashboard."""
        out = {}
        for cache in (self.records, self.quotes):
            hits = self.stats.get(f"{cache.name}.hits")
            misses = self.stats.get(f"{cache.name}.misses")
            total = hits + misses
            out[cache.name] = {
                "hits": hits,
                "misses": misses,
                "hit_ratio": (hits / total) if total else 0.0,
                "size": len(cache),
                "evictions": self.stats.get(f"{cache.name}.evictions"),
                "invalidations": self.stats.get(f"{cache.name}.invalidations"),
            }
        out["store"] = {"reads": self.store.reads, "writes": self.store.writes}
        return out
