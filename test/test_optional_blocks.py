"""副命令が読むブロックだけが、その副命令にとって必須である（ADR-0075）。

`run` と `lines` は 1 つの入力ファイルを共有し、読む場所だけが違う。片方しか読まない
ブロックは書かなくてもパースが通り、無いことを言うのはそれを読む `to_*` である。
"""

from __future__ import annotations

import copy
import json

import pytest
from typer.testing import CliRunner

from fcenvelope import FCEnvelopeInput, load_lines
from fcenvelope.cli import app
from fcenvelope.errors import InvalidInputError

runner = CliRunner()

#: `lines` が読む位置だけを書いた入力。`broadening` も `grid` も無い。
LINES_ONLY = """\
schema_version = 4
temperature = 300.0

[modes]
coupling_convention = "g"

[[modes.rows]]
frequency = 1200.0
coupling = 0.5

[selection]
min_weight = 0.0001
"""


@pytest.fixture
def lines_only_file(tmp_path):
    path = tmp_path / "lines_only.toml"
    path.write_text(LINES_ONLY, encoding="utf-8")
    return path


def test_parses_without_the_blocks_only_run_reads():
    """`broadening` / `grid` が無くてもパースは通る。構造の検査は必要性を見ない。"""
    parsed = FCEnvelopeInput.from_toml(LINES_ONLY)

    assert parsed.broadening is None
    assert parsed.grid is None
    assert parsed.to_temperature() == 300.0
    assert parsed.to_system().modes[0].huang_rhys == 0.25
    assert parsed.to_selection().min_weight == 0.0001


@pytest.mark.parametrize(
    ("block", "reader"),
    [("broadening", "to_broadening"), ("grid", "to_grid")],
)
def test_missing_block_is_reported_by_the_reader(block, reader):
    """報告はブロック名と、それを必要とする副命令の両方を言う。"""
    parsed = FCEnvelopeInput.from_toml(LINES_ONLY)

    with pytest.raises(InvalidInputError) as raised:
        getattr(parsed, reader)()

    message = str(raised.value)
    assert message.startswith(f"{block}: ")
    assert "fcenvelope run" in message


def test_selection_is_filled_with_defaults_instead(input_payload):
    """`selection` だけは既定値で埋まる。つまみには分子によらない既定がある。"""
    payload = copy.deepcopy(input_payload)
    payload.pop("selection", None)
    parsed = FCEnvelopeInput.from_obj(payload)

    assert parsed.to_selection().max_lines == 10000


def test_lines_runs_without_broadening_and_grid(tmp_path, lines_only_file):
    output = tmp_path / "out.json"
    invocation = runner.invoke(
        app, ["lines", str(lines_only_file), "-o", str(output), "--no-script"]
    )

    assert invocation.exit_code == 0, invocation.output
    assert load_lines(output).lines


def test_run_without_broadening_fails_naming_the_block(tmp_path, lines_only_file):
    output = tmp_path / "out.json"
    invocation = runner.invoke(
        app, ["run", str(lines_only_file), "-o", str(output), "--no-script"]
    )

    assert invocation.exit_code == 1
    assert "broadening: required by `fcenvelope run`" in invocation.output
    assert not output.exists()


def test_effective_settings_write_the_missing_blocks_as_null(tmp_path, lines_only_file):
    """実効設定は書かなかったブロックを `null` で見せる（ADR-0065, 0069）。"""
    output = tmp_path / "out.json"
    config = tmp_path / "used.json"
    invocation = runner.invoke(
        app,
        ["lines", str(lines_only_file), "-o", str(output), "--config", str(config),
         "--no-script"],
    )

    assert invocation.exit_code == 0, invocation.output
    written = json.loads(config.read_text(encoding="utf-8"))
    assert written["broadening"] is None
    assert written["grid"] is None
    # 書き返せば同じ計算になる。
    assert FCEnvelopeInput.from_path(config).to_selection().min_weight == 0.0001


def test_override_can_raise_a_missing_block(tmp_path, lines_only_file):
    """`null` のブロックは「無い」と同じに扱い、上書きで起こせる（ADR-0064, 0075）。"""
    output = tmp_path / "out.json"
    invocation = runner.invoke(
        app,
        [
            "run", str(lines_only_file), "-o", str(output), "--no-script",
            "--override", "broadening.sigma=150.0",
            "--override", "grid.e_min=-4500.0",
            "--override", "grid.e_max=1000.0",
            "--override", "grid.points.de=4.0",
        ],
    )

    assert invocation.exit_code == 0, invocation.output
    assert output.exists()
