"""Field-level validation rules shared by the service layer and the CLI."""

import re

from stockroom.errors import ValidationError

SKU_RE = re.compile(r"^[A-Z][A-Z0-9]{1,5}-\d{3,6}$")
LOCATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/-]{0,31}$")
MAX_NAME = 80
MAX_CUSTOMER = 60
MAX_QUANTITY = 1_000_000


def normalize_sku(sku):
    """Upper-case and strip a SKU, then check its shape (e.g. ``BOLT-0042``)."""
    if not isinstance(sku, str):
        raise ValidationError(f"SKU must be text, got {type(sku).__name__}")
    s = sku.strip().upper()
    if not SKU_RE.match(s):
        raise ValidationError(
            f"invalid SKU {sku!r}: expected letters, a dash and 3-6 digits (e.g. BOLT-0042)"
        )
    return s


def check_name(name):
    if not isinstance(name, str) or not name.strip():
        raise ValidationError("name must not be empty")
    name = " ".join(name.split())
    if len(name) > MAX_NAME:
        raise ValidationError(f"name is longer than {MAX_NAME} characters")
    return name


def check_quantity(qty, what="quantity", allow_zero=True):
    if isinstance(qty, bool) or not isinstance(qty, int):
        raise ValidationError(f"{what} must be an integer")
    if qty < 0 or (qty == 0 and not allow_zero):
        raise ValidationError(f"{what} must be {'>= 0' if allow_zero else '> 0'}, got {qty}")
    if qty > MAX_QUANTITY:
        raise ValidationError(f"{what} must be <= {MAX_QUANTITY}, got {qty}")
    return qty


def check_price_cents(cents):
    if isinstance(cents, bool) or not isinstance(cents, int):
        raise ValidationError("price must be an integer number of cents")
    if cents < 0:
        raise ValidationError(f"price must not be negative, got {cents}")
    return cents


def check_location(location):
    if location is None:
        return ""
    location = location.strip()
    if location == "":
        return ""
    if not LOCATION_RE.match(location):
        raise ValidationError(f"invalid location {location!r}")
    return location


def check_customer(customer):
    customer = (customer or "").strip()
    if len(customer) > MAX_CUSTOMER:
        raise ValidationError(f"customer is longer than {MAX_CUSTOMER} characters")
    return customer
