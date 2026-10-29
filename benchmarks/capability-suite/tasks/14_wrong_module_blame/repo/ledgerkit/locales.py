"""Number and date conventions for the locales a ledger file may declare.

A ledger file starts in ``en_US`` unless the caller says otherwise; a
``!locale`` directive switches the convention for the rest of that file only.
Rates files and directive arguments are always written in the "C" convention
(``.`` as the decimal mark, no grouping), whatever the active locale.
"""

from dataclasses import dataclass

from .errors import ParseError


@dataclass(frozen=True)
class LocaleSpec:
    name: str
    decimal: str
    groups: tuple                 # accepted digit-group separators
    date_formats: tuple           # strptime formats, tried in order
    display_group: str = ","
    display_decimal: str = "."

    def accepts_group(self, ch):
        return ch in self.groups


ISO = "%Y-%m-%d"

LOCALES = {
    "C": LocaleSpec("C", ".", (), (ISO,), "", "."),
    "en_US": LocaleSpec("en_US", ".", (",",), (ISO, "%m/%d/%Y"), ",", "."),
    "en_GB": LocaleSpec("en_GB", ".", (",",), (ISO, "%d/%m/%Y"), ",", "."),
    "de_DE": LocaleSpec("de_DE", ",", (".",), (ISO, "%d.%m.%Y"), ".", ","),
    "de_CH": LocaleSpec("de_CH", ".", ("'", "\u2019"), (ISO, "%d.%m.%Y"), "'", "."),
    "fr_FR": LocaleSpec("fr_FR", ",", (" ", "\u00a0", "\u202f"), (ISO, "%d/%m/%Y"), "\u202f", ","),
}

ALIASES = {
    "en": "en_US",
    "us": "en_US",
    "gb": "en_GB",
    "uk": "en_GB",
    "de": "de_DE",
    "ch": "de_CH",
    "fr": "fr_FR",
    "posix": "C",
}

DEFAULT_LOCALE = "en_US"


def get_locale(name):
    """Return the LocaleSpec for ``name`` (case-insensitive, ``-`` or ``_``)."""
    if isinstance(name, LocaleSpec):
        return name
    if name is None:
        name = DEFAULT_LOCALE
    key = name.strip().replace("-", "_")
    if key in LOCALES:
        return LOCALES[key]
    lowered = key.lower()
    if lowered in ALIASES:
        return LOCALES[ALIASES[lowered]]
    for k, spec in LOCALES.items():
        if k.lower() == lowered:
            return spec
    raise ParseError(f"unknown locale {name!r}")


def known_locales():
    return sorted(LOCALES)
