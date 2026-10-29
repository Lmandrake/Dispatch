from .base import SETTINGS as _BASE

SETTINGS = {**_BASE, "retries": 5, "timeout": 60}
