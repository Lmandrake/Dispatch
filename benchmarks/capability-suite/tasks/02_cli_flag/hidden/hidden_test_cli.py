import json
import subprocess
import sys

import pytest
from wordstat.cli import main
from wordstat.counting import count_words, top_words

TEXT = "I am a big cat. A cat is an animal; cats are big. Go go go!"


def run(tmp_path, capsys, *args):
    f = tmp_path / "t.txt"
    f.write_text(TEXT)
    assert main([str(f), "--json", *args]) == 0
    return json.loads(capsys.readouterr().out)


def test_default_unchanged(tmp_path, capsys):
    out = run(tmp_path, capsys)
    assert out["total"] == 16
    assert out["top"][0] == ["go", 3]


def test_min_length_filters_top_and_total(tmp_path, capsys):
    out = run(tmp_path, capsys, "--min-length", "3")
    words = dict((w, c) for w, c in out["top"])
    assert all(len(w) >= 3 for w in words)
    assert words["cat"] == 2 and words["big"] == 2
    # big cat cat animal cats are big -> 7 words of length >= 3
    assert out["total"] == 7
    assert out["unique"] == 5


def test_min_length_one_is_noop(tmp_path, capsys):
    assert run(tmp_path, capsys, "--min-length", "1") == run(tmp_path, capsys)


def test_text_mode(tmp_path, capsys):
    f = tmp_path / "t.txt"
    f.write_text(TEXT)
    main([str(f), "--min-length", "4"])
    out = capsys.readouterr().out
    assert "total: 2" in out
    assert "animal" in out and "cats" in out and " go" not in out


def test_combined_with_case_sensitive(tmp_path, capsys):
    out = run(tmp_path, capsys, "--min-length", "2", "--case-sensitive")
    words = dict((w, c) for w, c in out["top"])
    assert "A" not in words and "I" not in words and "a" not in words
    assert words.get("go") == 2 and words.get("Go") == 1


@pytest.mark.parametrize("bad", ["0", "-2", "abc", "2.5"])
def test_rejects_bad_values(tmp_path, bad):
    f = tmp_path / "t.txt"
    f.write_text(TEXT)
    with pytest.raises(SystemExit) as e:
        main([str(f), "--min-length", bad])
    assert e.value.code == 2


def test_library_keyword():
    c = count_words(TEXT, min_length=4)
    assert set(c) == {"animal", "cats"}
    c2 = count_words(TEXT)
    assert c2["a"] == 2
    assert top_words(c2, 1) == [("go", 3)]


def test_module_entrypoint(tmp_path):
    f = tmp_path / "t.txt"
    f.write_text(TEXT)
    r = subprocess.run([sys.executable, "-m", "wordstat", str(f), "--json", "--min-length", "5"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["total"] == 1
