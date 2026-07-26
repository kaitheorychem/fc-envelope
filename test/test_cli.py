"""CLI の疎通と終了コード（合意文書 §9.1）。"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from fcenvelope import load_result
from fcenvelope.cli import app

runner = CliRunner()


@pytest.fixture
def input_file(tmp_path, input_payload):
    path = tmp_path / "input.json"
    path.write_text(json.dumps(input_payload), encoding="utf-8")
    return path


def test_run_writes_a_result(tmp_path, input_file):
    output = tmp_path / "result.json"
    invocation = runner.invoke(app, ["run", str(input_file), "-o", str(output)])

    assert invocation.exit_code == 0, invocation.output
    result = load_result(output)
    assert result.energy.size > 0
    assert result.conditions.temperature == 300.0
    assert result.modes[0].huang_rhys == 0.25


def test_run_with_plot(tmp_path, input_file):
    output = tmp_path / "result.json"
    figure = tmp_path / "figure.png"
    invocation = runner.invoke(
        app, ["run", str(input_file), "-o", str(output), "--plot", str(figure)]
    )

    assert invocation.exit_code == 0, invocation.output
    assert figure.is_file()
    assert figure.stat().st_size > 0


def test_run_overrides_conditions(tmp_path, input_file):
    output = tmp_path / "result.json"
    invocation = runner.invoke(
        app,
        [
            "run",
            str(input_file),
            "-o",
            str(output),
            "--temperature",
            "0",
            "--sigma",
            "80",
            "--e-min",
            "-6000",
            "--e-max",
            "2000",
            "--de",
            "4",
        ],
    )

    assert invocation.exit_code == 0, invocation.output
    conditions = load_result(output).conditions
    assert conditions.temperature == 0.0
    assert conditions.sigma == 80.0
    assert conditions.e_min == -6000.0
    assert conditions.e_max == 2000.0
    assert conditions.de == 4.0


def test_run_leaves_unspecified_conditions_untouched(tmp_path, input_file):
    output = tmp_path / "result.json"
    invocation = runner.invoke(
        app, ["run", str(input_file), "-o", str(output), "--temperature", "77"]
    )

    assert invocation.exit_code == 0, invocation.output
    conditions = load_result(output).conditions
    assert conditions.temperature == 77.0
    assert conditions.sigma == 150.0
    assert conditions.de == 5.0


def test_plot_subcommand(tmp_path, input_file):
    output = tmp_path / "result.json"
    assert runner.invoke(app, ["run", str(input_file), "-o", str(output)]).exit_code == 0

    figure = tmp_path / "figure.png"
    invocation = runner.invoke(
        app, ["plot", str(output), "-o", str(figure), "--title", "demo", "--dpi", "72"]
    )

    assert invocation.exit_code == 0, invocation.output
    assert figure.is_file()


def test_invalid_input_exits_with_one(tmp_path, input_payload):
    input_payload["frequency_unit"] = "eV"
    path = tmp_path / "input.json"
    path.write_text(json.dumps(input_payload), encoding="utf-8")

    invocation = runner.invoke(app, ["run", str(path), "-o", str(tmp_path / "out.json")])

    assert invocation.exit_code == 1
    assert "error:" in invocation.output
    assert "eV" in invocation.output


def test_bad_override_exits_with_one(tmp_path, input_file):
    invocation = runner.invoke(
        app, ["run", str(input_file), "-o", str(tmp_path / "out.json"), "--e-min", "5000"]
    )
    assert invocation.exit_code == 1
    assert "error:" in invocation.output


def test_missing_input_file_exits_with_one(tmp_path):
    invocation = runner.invoke(
        app, ["run", str(tmp_path / "absent.json"), "-o", str(tmp_path / "out.json")]
    )
    assert invocation.exit_code == 1


def test_usage_error_exits_with_two(tmp_path, input_file):
    invocation = runner.invoke(app, ["run", str(input_file)])
    assert invocation.exit_code == 2


def test_unknown_command_exits_with_two():
    assert runner.invoke(app, ["nope"]).exit_code == 2


def test_help_and_version():
    assert runner.invoke(app, ["--help"]).exit_code == 0
    version = runner.invoke(app, ["--version"])
    assert version.exit_code == 0
    assert version.output.strip()
