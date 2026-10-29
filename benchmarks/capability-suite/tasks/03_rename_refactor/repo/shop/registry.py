"""Named operations, resolved lazily so plugins can be swapped by config."""
import importlib

OPERATIONS = {
    "subtotal": "shop.pricing:subtotal",
    "total": "shop.pricing:calc_total",
    "invoice": "shop.invoice:render_invoice",
}


def resolve(name):
    module_name, attr = OPERATIONS[name].split(":")
    return getattr(importlib.import_module(module_name), attr)


def run(name, *args, **kwargs):
    return resolve(name)(*args, **kwargs)
