"""Replay the simulated relay session and print the event log (one record per line)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from relaylog.formatters import FORMATTERS
from relaylog.sim import events


def main():
    out = sys.stdout
    for e in events():
        out.write(FORMATTERS[e["kind"]](e) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
