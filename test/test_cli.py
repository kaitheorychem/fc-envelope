"""CLI の疎通と終了コード（合意文書 §9.1）。"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from fcenvelope import load_fc_lines, load_result
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


def test_run_reads_modes_from_referenced_csv(tmp_path, input_payload):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "modes.csv").write_text(
        "frequency,coupling\n1200.0,0.5\n450.0,0.8\n", encoding="utf-8"
    )
    input_payload["modes"] = {"path": "modes.csv"}
    path = data_dir / "input.json"
    path.write_text(json.dumps(input_payload), encoding="utf-8")
    output = tmp_path / "result.json"

    invocation = runner.invoke(app, ["run", str(path), "-o", str(output)])

    assert invocation.exit_code == 0, invocation.output
    modes = load_result(output).modes
    assert [mode.frequency for mode in modes] == [1200.0, 450.0]
    assert modes[0].huang_rhys == 0.25


def test_broken_modes_csv_exits_with_one(tmp_path, input_payload):
    (tmp_path / "modes.csv").write_text("frequency,coupling\n1200.0,oops\n", encoding="utf-8")
    input_payload["modes"] = {"path": "modes.csv"}
    path = tmp_path / "input.json"
    path.write_text(json.dumps(input_payload), encoding="utf-8")

    invocation = runner.invoke(app, ["run", str(path), "-o", str(tmp_path / "out.json")])

    assert invocation.exit_code == 1
    assert "modes.csv:2" in invocation.output


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


# --- lines サブコマンド ---


def test_lines_writes_a_line_list(tmp_path, input_file):
    output = tmp_path / "lines.json"
    invocation = runner.invoke(app, ["lines", str(input_file), "-o", str(output)])

    assert invocation.exit_code == 0, invocation.output
    result = load_fc_lines(output)
    assert result.diagnostics.n_lines > 0
    assert result.temperature == 300.0
    assert result.modes[0].huang_rhys == 0.25
    assert result.lines[0].energy == 0.0


def test_lines_prints_the_strongest_transitions(tmp_path, input_file):
    output = tmp_path / "lines.json"
    invocation = runner.invoke(
        app, ["lines", str(input_file), "-o", str(output), "--show", "3"]
    )

    assert invocation.exit_code == 0, invocation.output
    assert "ZPL" in invocation.output
    assert "more" in invocation.output
    assert invocation.output.count("->") >= 1


def test_lines_show_zero_prints_no_table(tmp_path, input_file):
    output = tmp_path / "lines.json"
    invocation = runner.invoke(
        app, ["lines", str(input_file), "-o", str(output), "--show", "0"]
    )
    assert invocation.exit_code == 0, invocation.output
    assert "ZPL" not in invocation.output


def test_lines_overrides_the_temperature(tmp_path, input_file):
    output = tmp_path / "lines.json"
    invocation = runner.invoke(
        app,
        [
            "lines", str(input_file), "-o", str(output),
            "--temperature", "0", "--min-intensity", "1e-6", "--max-lines", "500",
        ],
    )

    assert invocation.exit_code == 0, invocation.output
    result = load_fc_lines(output)
    assert result.temperature == 0.0
    assert result.min_intensity == 1e-6
    assert result.max_lines == 500
    assert result.diagnostics.max_initial_quanta == 0


def test_lines_with_plot(tmp_path, input_file):
    output = tmp_path / "lines.json"
    figure = tmp_path / "sticks.png"
    invocation = runner.invoke(
        app, ["lines", str(input_file), "-o", str(output), "--plot", str(figure)]
    )

    assert invocation.exit_code == 0, invocation.output
    assert figure.is_file() and figure.stat().st_size > 0


def test_plot_subcommand_renders_a_stored_line_list(tmp_path, input_file):
    output = tmp_path / "lines.json"
    assert runner.invoke(app, ["lines", str(input_file), "-o", str(output)]).exit_code == 0

    figure = tmp_path / "sticks.png"
    invocation = runner.invoke(app, ["plot", str(output), "-o", str(figure)])

    assert invocation.exit_code == 0, invocation.output
    assert figure.is_file()


def test_lines_bad_threshold_exits_with_one(tmp_path, input_file):
    invocation = runner.invoke(
        app,
        ["lines", str(input_file), "-o", str(tmp_path / "out.json"), "--min-intensity", "0"],
    )
    assert invocation.exit_code == 1
    assert "error:" in invocation.output


def test_lines_invalid_input_exits_with_one(tmp_path, input_payload):
    input_payload["schema_version"] = 99
    path = tmp_path / "input.json"
    path.write_text(json.dumps(input_payload), encoding="utf-8")

    invocation = runner.invoke(
        app, ["lines", str(path), "-o", str(tmp_path / "out.json")]
    )
    assert invocation.exit_code == 1
    assert "error:" in invocation.output
