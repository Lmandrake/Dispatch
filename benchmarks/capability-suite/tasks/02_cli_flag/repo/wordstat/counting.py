"""Word counting primitives."""
import re
from collections import Counter

WORD_RE = re.compile(r"[a-z0-9']+")


def tokenize(text, lowercase=True):
    if lowercase:
        text = text.lower()
        return WORD_RE.findall(text)
    return re.findall(r"[A-Za-z0-9']+", text)


def count_words(text, lowercase=True):
    """Return a Counter of word -> occurrences."""
    return Counter(tokenize(text, lowercase=lowercase))


def top_words(counter, n=10):
    """Most common words, ties broken alphabetically."""
    return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
