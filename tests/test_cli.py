from thebundl.__main__ import main


def test_check_config_does_not_print_secret(monkeypatch, capsys):
    monkeypatch.setenv("GROQ_API_KEY", "must-not-be-printed")
    assert main(["check-config"]) == 0
    output = capsys.readouterr().out
    assert "GROQ_API_KEY: set" in output
    assert "must-not-be-printed" not in output


def test_run_dry_run_writes_an_artifact(monkeypatch, tmp_path):
    monkeypatch.setenv("WORK_DIR", str(tmp_path))
    assert main(["run", "--dry-run", "--limit", "5"]) == 3
    assert list(tmp_path.glob("*-run.json"))
