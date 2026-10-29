import json
from wordstat.cli import main


def test_json_output(tmp_path, capsys):
    f = tmp_path / "a.txt"
    f.write_text("The cat and the hat. The end.")
    assert main([str(f), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["total"] == 7
    assert out["top"][0] == ["the", 3]
