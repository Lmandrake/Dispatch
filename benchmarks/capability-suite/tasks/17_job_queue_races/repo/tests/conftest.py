import pytest

from taskmill import Broker, BrokerConfig, ManualClock


@pytest.fixture
def clock():
    return ManualClock(1_000_000.0)


@pytest.fixture
def broker(clock):
    b = Broker(None, BrokerConfig(visibility_timeout=30), clock=clock)
    yield b
    b.close()


@pytest.fixture
def durable(tmp_path, clock):
    b = Broker(str(tmp_path / "data"), BrokerConfig(visibility_timeout=30), clock=clock)
    yield b
    b.close()
