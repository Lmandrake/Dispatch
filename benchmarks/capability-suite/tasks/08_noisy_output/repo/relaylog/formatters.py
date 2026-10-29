"""Line formatters: one per event kind. Hot path, so no json.dumps per record."""
import datetime


def q(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def num(x):
    return "null" if x is None else repr(x)


def ts(t):
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def fmt_connect(e):
    return '%s INFO {"kind": "connect", "peer": %s, "seq": %d}' % (ts(e["t"]), q(e["peer"]), e["seq"])


def fmt_disconnect(e):
    return '%s INFO {"kind": "disconnect", "peer": %s, "seq": %d, "ms": %s}' % (ts(e["t"]), q(e["peer"]), e["seq"], e["ms"])


def fmt_auth(e):
    return '%s INFO {"kind": "auth", "peer": %s, "user": %s}' % (ts(e["t"]), q(e["peer"]), q(e["user"]))


def fmt_auth_fail(e):
    return '%s WARN {"kind": "auth_fail", "peer": %s, "user": %s, "attempt": %d}' % (ts(e["t"]), q(e["peer"]), q(e["user"]), e["attempt"])


def fmt_send(e):
    return '%s DEBUG {"kind": "send", "peer": %s, "bytes": %d, "ms": %s}' % (ts(e["t"]), q(e["peer"]), e["size"], e["ms"])


def fmt_recv(e):
    return '%s DEBUG {"kind": "recv", "peer": %s, "bytes": %d, "ms": %s}' % (ts(e["t"]), q(e["peer"]), e["size"], e["ms"])


def fmt_ack(e):
    return '%s DEBUG {"kind": "ack", "seq": %d, "ms": %s}' % (ts(e["t"]), e["seq"], e["ms"])


def fmt_nack(e):
    return '%s WARN {"kind": "nack", "seq": %d, "peer": %s}' % (ts(e["t"]), e["seq"], q(e["peer"]))


def fmt_retry(e):
    return '%s WARN {"kind": "retry", "seq": %d, "attempt": %d, "delay_ms": %s}' % (ts(e["t"]), e["seq"], e["attempt"], e["delay"])


def fmt_throttle(e):
    return '%s WARN {"kind": "throttle", "peer": %s, "delay_ms": %s}' % (ts(e["t"]), q(e["peer"]), num(e["delay"]))


def fmt_heartbeat(e):
    return '%s DEBUG {"kind": "heartbeat", "peer": %s, "ms": %s}' % (ts(e["t"]), q(e["peer"]), e["ms"])


def fmt_gc(e):
    return '%s INFO {"kind": "gc", "freed": %d}' % (ts(e["t"]), e["size"])


def fmt_rotate(e):
    return '%s INFO {"kind": "rotate", "bytes": %d}' % (ts(e["t"]), e["size"])


def fmt_flush(e):
    return '%s DEBUG {"kind": "flush", "bytes": %d, "ms": %s}' % (ts(e["t"]), e["size"], e["ms"])


def fmt_spill(e):
    return '%s WARN {"kind": "spill", "bytes": %d}' % (ts(e["t"]), e["size"])


def fmt_resume(e):
    return '%s INFO {"kind": "resume", "peer": %s, "delay_ms": %s}' % (ts(e["t"]), q(e["peer"]), num(e["delay"]))


def fmt_pause(e):
    return '%s INFO {"kind": "pause", "peer": %s}' % (ts(e["t"]), q(e["peer"]))


def fmt_config(e):
    return '%s INFO {"kind": "config", "user": %s}' % (ts(e["t"]), q(e["user"]))


def fmt_quota(e):
    return '%s WARN {"kind": "quota", "user": %s, "bytes": %d}' % (ts(e["t"]), q(e["user"]), e["size"])


def fmt_drain(e):
    return '%s INFO {"kind": "drain", "peer": %s, "ms": %s}' % (ts(e["t"]), q(e["peer"]), e["ms"])


FORMATTERS = {
    "connect": fmt_connect,
    "disconnect": fmt_disconnect,
    "auth": fmt_auth,
    "auth_fail": fmt_auth_fail,
    "send": fmt_send,
    "recv": fmt_recv,
    "ack": fmt_ack,
    "nack": fmt_nack,
    "retry": fmt_retry,
    "throttle": fmt_throttle,
    "heartbeat": fmt_heartbeat,
    "gc": fmt_gc,
    "rotate": fmt_rotate,
    "flush": fmt_flush,
    "spill": fmt_spill,
    "resume": fmt_resume,
    "pause": fmt_pause,
    "config": fmt_config,
    "quota": fmt_quota,
    "drain": fmt_drain,
}
