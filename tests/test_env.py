import os

from env import load_env


def _write(tmp_path, body):
    path = tmp_path / ".env"
    path.write_text(body)
    return path


def test_loads_values(tmp_path, monkeypatch):
    monkeypatch.delenv("PDT_TEST_KEY", raising=False)
    load_env(_write(tmp_path, "PDT_TEST_KEY=hello\n"))
    assert os.environ["PDT_TEST_KEY"] == "hello"


def test_blank_values_are_treated_as_unset(tmp_path, monkeypatch):
    # A blank entry must not export "", or int(os.environ.get(k, default)) breaks.
    monkeypatch.delenv("PDT_BLANK", raising=False)
    load_env(_write(tmp_path, "PDT_BLANK=\n"))
    assert "PDT_BLANK" not in os.environ


def test_real_environment_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("PDT_TEST_KEY", "from-shell")
    load_env(_write(tmp_path, "PDT_TEST_KEY=from-file\n"))
    assert os.environ["PDT_TEST_KEY"] == "from-shell"


def test_ignores_comments_quotes_and_junk(tmp_path, monkeypatch):
    monkeypatch.delenv("PDT_QUOTED", raising=False)
    monkeypatch.delenv("PDT_COMMENT", raising=False)
    load_env(_write(tmp_path, '# PDT_COMMENT=nope\nnot-a-pair\nPDT_QUOTED="spaced value"\n'))
    assert os.environ["PDT_QUOTED"] == "spaced value"
    assert "PDT_COMMENT" not in os.environ


def test_missing_file_is_a_no_op(tmp_path):
    load_env(tmp_path / "does-not-exist")
