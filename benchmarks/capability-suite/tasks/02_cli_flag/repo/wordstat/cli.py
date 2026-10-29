"""Command line entry point: python -m wordstat FILE [options]."""
import argparse
import json
import sys

from .counting import count_words, top_words


def build_parser():
    p = argparse.ArgumentParser(prog="wordstat", description="Count words in a text file.")
    p.add_argument("path", help="file to read, or - for stdin")
    p.add_argument("-n", "--top", type=int, default=10, help="how many top words to show")
    p.add_argument("--case-sensitive", action="store_true", help="do not lowercase words")
    p.add_argument("--json", action="store_true", help="emit JSON instead of text")
    return p


def _read(path):
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def main(argv=None):
    args = build_parser().parse_args(argv)
    text = _read(args.path)
    counts = count_words(text, lowercase=not args.case_sensitive)
    top = top_words(counts, args.top)
    total = sum(counts.values())
    if args.json:
        print(json.dumps({"total": total, "unique": len(counts), "top": [[w, c] for w, c in top]}))
    else:
        print(f"total: {total}")
        print(f"unique: {len(counts)}")
        for w, c in top:
            print(f"{c:6d} {w}")
    return 0
