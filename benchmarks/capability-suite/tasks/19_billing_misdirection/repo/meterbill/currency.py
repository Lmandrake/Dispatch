"""Currency registry: ISO code, minor-unit exponent, symbol, display style.

The exponent is the number of decimal places of the currency's minor unit
(2 for USD cents, 0 for JPY).  All rounding to "the currency" goes through
``Currency.quantum``.
"""

from dataclasses import dataclass
from decimal import Decimal

from .errors import ConfigError


@dataclass(frozen=True)
class Currency:
    code: str
    exponent: int
    symbol: str
    name: str
    symbol_first: bool = True

    @property
    def quantum(self):
        """The Decimal step of one minor unit, e.g. Decimal('0.01')."""
        return Decimal(1).scaleb(-self.exponent)

    def __str__(self):
        return self.code


_REGISTRY = {}


def register(code, exponent, symbol, name, symbol_first=True):
    if not (isinstance(code, str) and len(code) == 3 and code.isupper()):
        raise ConfigError(f"bad currency code {code!r}")
    if exponent not in (0, 2, 3):
        raise ConfigError(f"unsupported exponent {exponent} for {code}")
    cur = Currency(code, exponent, symbol, name, symbol_first)
    _REGISTRY[code] = cur
    return cur


register("USD", 2, "$", "US dollar")
register("EUR", 2, "€", "Euro")
register("GBP", 2, "£", "Pound sterling")
register("CHF", 2, "CHF ", "Swiss franc")
register("JPY", 0, "¥", "Japanese yen")
register("SEK", 2, " kr", "Swedish krona", symbol_first=False)
register("CAD", 2, "CA$", "Canadian dollar")
register("KWD", 3, "KD ", "Kuwaiti dinar")


def get(code):
    """Return the Currency for an ISO code (case-insensitive)."""
    if isinstance(code, Currency):
        return code
    try:
        return _REGISTRY[str(code).strip().upper()]
    except KeyError:
        raise ConfigError(f"unknown currency {code!r}") from None


def known():
    """Sorted list of registered currency codes."""
    return sorted(_REGISTRY)


def exponent(code):
    return get(code).exponent
register("AUD", 2, "A$", "Australian dollar")
