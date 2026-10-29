"""python3 -m tally FILE  (SPEC.md section 1)."""

import sys

from . import run
from .errors import TallyError


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: python3 -m tally FILE", file=sys.stderr)
        return 2
    with open(argv[0], encoding="utf-8") as f:
        src = f.read()
    try:
        out = run(src)
    except TallyError as exc:
        sys.stdout.write(exc.output)
        sys.stdout.flush()
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
