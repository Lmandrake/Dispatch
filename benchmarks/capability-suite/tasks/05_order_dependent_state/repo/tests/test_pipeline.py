from etl import Pipeline


def test_single_step():
    p = Pipeline("double")

    @p.step
    def double(d):
        return {**d, "x": d["x"] * 2}

    out, errors = p.run([{"x": 1}, {"x": 5}])
    assert [r.data["x"] for r in out] == [2, 10]
    assert errors == []


def test_history():
    p = Pipeline("inc")

    @p.step
    def inc(d):
        return {**d, "x": d["x"] + 1}

    out, _ = p.run([{"x": 1}])
    assert out[0].history == ["inc"]
