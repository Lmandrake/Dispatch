import subprocess
import sys

import pytest
from etl import Pipeline, Record


def make(name, **opts):
    return Pipeline(name, **opts)


def test_steps_isolated_between_instances():
    a, b = make("a"), make("b")
    a.step(lambda d: {**d, "x": d["x"] * 10})
    out, _ = b.run([{"x": 1}])
    assert out[0].data == {"x": 1}
    out, _ = a.run([{"x": 1}])
    assert out[0].data == {"x": 10}


def test_options_isolated_between_instances():
    lenient = make("l", skip_errors=True)
    strict = make("s")
    assert lenient.options["skip_errors"] is True
    assert strict.options["skip_errors"] is False

    def boom(d):
        raise ValueError("x")
    strict.step(boom)
    with pytest.raises(ValueError):
        strict.run([{}])
    lenient.step(boom)
    out, errors = lenient.run([{}])
    assert out == [] and len(errors) == 1


def test_records_have_own_history():
    r1, r2 = Record({"a": 1}), Record({"a": 2})
    r1.note("s1")
    assert r2.history == []
    assert r1.history == ["s1"]
    # An explicit history may be kept or copied: the prompt never says which, so only check
    # that it is honoured and that it does not leak into fresh records.
    r3 = Record({}, ["x"])
    r3.note("z")
    assert r3.history == ["x", "z"]
    assert Record({}).history == []


def test_history_per_row():
    p = make("h")

    @p.step
    def one(d):
        return d

    @p.step
    def two(d):
        return d

    out, _ = p.run([{"i": i} for i in range(3)])
    assert [r.history for r in out] == [["one", "two"]] * 3


def test_skip_errors_still_works():
    p = make("parse", skip_errors=True)

    @p.step
    def parse(d):
        return {**d, "n": int(d["s"])}

    out, errors = p.run([{"s": "1"}, {"s": "oops"}, {"s": "3"}])
    assert [r.data["n"] for r in out] == [1, 3]
    assert [r.history for r in out] == [["parse"], ["parse"]]
    assert len(errors) == 1 and isinstance(errors[0][1], ValueError)


@pytest.mark.parametrize("order", [["tests/test_pipeline.py", "tests/test_errors.py"],
                                   ["tests/test_errors.py", "tests/test_pipeline.py"]])
def test_visible_suite_passes_in_any_order(order):
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:randomly", *order],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:]
