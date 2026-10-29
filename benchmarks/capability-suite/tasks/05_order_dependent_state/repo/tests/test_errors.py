import pytest
from etl import Pipeline


def test_skip_errors():
    p = Pipeline("parse", skip_errors=True)

    @p.step
    def parse(d):
        return {**d, "n": int(d["s"])}

    out, errors = p.run([{"s": "1"}, {"s": "oops"}, {"s": "3"}])
    assert [r.data["n"] for r in out] == [1, 3]
    assert len(errors) == 1


def test_errors_raise_by_default():
    p = Pipeline("strict")

    @p.step
    def boom(d):
        raise RuntimeError("bad row")

    with pytest.raises(RuntimeError):
        p.run([{"a": 1}])
