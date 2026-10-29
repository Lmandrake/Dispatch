import random
import time

from intervals import find_overlaps


def test_small():
    iv = [("a", 0, 10), ("b", 5, 15), ("c", 10, 20), ("d", 30, 31)]
    assert find_overlaps(iv) == [("a", "b"), ("b", "c")]


def test_large_input():
    rnd = random.Random(0)
    iv = []
    t = 0
    for i in range(200_000):
        t += rnd.randint(0, 50)
        iv.append((i, t, t + rnd.randint(1, 120)))
    rnd.shuffle(iv)
    t0 = time.perf_counter()
    res = find_overlaps(iv)
    assert time.perf_counter() - t0 < 3
    assert len(res) > 100_000
