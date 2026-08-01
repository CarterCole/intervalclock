from intervalclock.cli import main


def test_name_cron(capsys):
    assert main(["name", "--cron", "*/5 * * * *"]) == 0
    out = capsys.readouterr().out
    assert "ic1:k:0-55/5|*|*|*|*" in out
    assert "IC1-" in out and "alias:" in out


def test_name_period_state(capsys):
    assert main(["name", "--period", "1/3", "--states", "3", "--state", "2"]) == 0
    assert "ic1:c:w=1/3;m=3;phi=2/3" in capsys.readouterr().out


def test_name_hz(capsys):
    assert main(["name", "--hz", "15/2"]) == 0
    assert "ic1:c:w=1/15;m=2;phi=0" in capsys.readouterr().out


def test_name_cell_and_parse(capsys):
    assert main(["name", "2026-08-01T14"]) == 0
    out = capsys.readouterr().out
    assert "ic1:g:2026-08-01T14" in out
    assert main(["parse", "ic1:g:2026-08-01T14"]) == 0
    assert "ic1:s:1785592837;1785596437" in capsys.readouterr().out


def test_next_and_contains(capsys):
    assert main(["next", "ic1:c:w=1/3;m=3;phi=2/3", "-n", "2", "--from", "0"]) == 0
    out = capsys.readouterr().out
    assert "[2/3, 1)" in out
    assert main(["contains", "ic1:c:w=1/3;m=3;phi=2/3", "5/6"]) == 0
    assert main(["contains", "ic1:c:w=1/3;m=3;phi=2/3", "1/6"]) == 1


def test_now_runs(capsys):
    assert main(["now", "--of", "ic1:c:w=1/3;m=3;phi=0"]) == 0
    out = capsys.readouterr().out
    assert "tai:" in out and "grid:" in out


def test_alias_cmd(capsys):
    assert main(["alias", "ic1:c:w=1/3;m=3;phi=2/3"]) == 0
    assert len(capsys.readouterr().out.strip().split("-")) == 4


def test_error_paths(capsys):
    assert main(["parse", "ic1:bogus:xyz"]) == 2
    assert main(["name"]) == 2
