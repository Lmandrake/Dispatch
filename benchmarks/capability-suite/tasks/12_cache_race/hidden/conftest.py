import signal

import pytest

LIMIT_S = 60


@pytest.fixture(autouse=True)
def _wall_clock_limit():
    def boom(signum, frame):
        raise TimeoutError(f"test exceeded {LIMIT_S}s wall clock")
    old = signal.signal(signal.SIGALRM, boom)
    signal.alarm(LIMIT_S)
    yield
    signal.alarm(0)
    signal.signal(signal.SIGALRM, old)
