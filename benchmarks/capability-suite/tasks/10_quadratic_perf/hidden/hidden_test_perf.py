import random
import time

import pytest
from intervals import find_overlaps


def brute(iv):
    out = []
    for i in range(len(iv)):
        for j in range(i + 1, len(iv)):
            a, b = iv[i], iv[j]
            if a[1] < b[2] and b[1] < a[2]:
                out.append((a[0], b[0]) if a[0] < b[0] else (b[0], a[0]))
    return sorted(out)


def test_doc_examples():
    assert find_overlaps([]) == []
    assert find_overlaps([("x", 1, 2)]) == []
    assert find_overlaps([("a", 0, 10), ("b", 10, 20)]) == []
    assert find_overlaps([("b", 0, 10), ("a", 9, 20)]) == [("a", "b")]
    assert find_overlaps([("z", 0, 100), ("y", 1, 2), ("x", 2, 3)]) == [("x", "z"), ("y", "z")]


@pytest.mark.parametrize("seed", range(40))
def test_matches_bruteforce(seed):
    rnd = random.Random(seed)
    n = rnd.randint(0, 120)
    iv = []
    for i in rnd.sample(range(1000), n):
        s = rnd.choice([rnd.randint(0, 60), rnd.uniform(0, 60)])
        iv.append((i, s, s + rnd.choice([1, 2, 5, 10, rnd.uniform(0.01, 20)])))
    assert find_overlaps(list(iv)) == brute(iv)


def test_identical_and_nested_and_touching():
    iv = [(1, 0, 5), (2, 0, 5), (3, 5, 9), (4, 1, 2), (5, 4, 6), (6, 9, 10), (7, -3, 0)]
    assert find_overlaps(iv) == brute(iv)


def test_input_not_mutated():
    iv = [(3, 5, 9), (1, 0, 6), (2, 1, 2)]
    copy = list(iv)
    find_overlaps(iv)
    assert iv == copy


def test_time_bound():
    rnd = random.Random(42)
    iv, t = [], 0
    for i in range(300_000):
        t += rnd.randint(0, 50)
        iv.append((f"bk{i:07d}", t, t + rnd.randint(1, 120)))
    rnd.shuffle(iv)
    t0 = time.perf_counter()
    res = find_overlaps(iv)
    elapsed = time.perf_counter() - t0
    assert elapsed < 4.0, elapsed
    # spot-check correctness on a window
    assert res == sorted(set(res))
    assert all(a < b for a, b in res)
    sub = sorted(iv, key=lambda x: x[1])[1000:1400]
    ids = {x[0] for x in sub}
    want = set(brute(sub))
    got = {p for p in res if p[0] in ids and p[1] in ids}
    assert got == want
