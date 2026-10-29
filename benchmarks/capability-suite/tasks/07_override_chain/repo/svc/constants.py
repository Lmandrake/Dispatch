"""Compile-time defaults. Most of these are overridden at runtime; see svc/settings.py."""
DEFAULT_TIMEOUT = 30          # seconds; fallback only
DEFAULT_RETRIES = 3
DEFAULT_PORT = 8710
MAX_PAYLOAD = 1 << 20
POLL_INTERVAL = 5
