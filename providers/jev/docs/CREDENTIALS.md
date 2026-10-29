# Credentials

The TypeSafe API key is **not** in this repo and must never be committed to it.

It lives at `the consultjev env file`, mode `600`:

```
TYPESAFE_API_KEY=apikey_...
TYPESAFE_ACCOUNT=...
```

`consultjev.client.load_api_key()` reads `TYPESAFE_API_KEY` from the environment first and
falls back to that file. It raises with the console URL rather than returning `None`,
because a missing key otherwise surfaces as a `401` several frames away from its cause.

Keys are created and revoked at <https://console.typesafe.ai/keys>.

## Private overlay

Account ownership and rotation history are kept out of this repo, in an optional overlay (`<overlay>/jev/ACCOUNT.md`, found by `dispatchlib/providers.py`).
The overlay's `overlay.json` may also name a different key file with `credentials_file`.
With no overlay and no key, the probe reports `not configured` and the router runs on.
