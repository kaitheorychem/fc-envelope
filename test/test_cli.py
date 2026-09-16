"""CLI の疎通と終了コード（合意文書 §9.1）。"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from fcenvelope import load_lines, load_envelope
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
    result = load_envelope(output)
    assert result.energy.size > 0
    assert result.temperature == 300.0
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
            "--gamma",
            "30",
            "--e-min",
            "-6000",
            "--e-max",
            "2000",
            "--de",
            "4",
        ],
    )

    assert invocation.exit_code == 0, invocation.output
    result = load_envelope(output)
    assert result.temperature == 0.0
    assert result.broadening.sigma == 80.0
    assert result.broadening.gamma == 30.0
    assert result.grid.e_min == -6000.0
    assert result.grid.e_max == 2000.0
    assert result.grid.de == 4.0


def test_run_leaves_unspecified_conditions_untouched(tmp_path, input_file):
    output = tmp_path / "result.json"
    invocation = runner.invoke(
        app, ["run", str(input_file), "-o", str(output), "--temperature", "77"]
    )

    assert invocation.exit_code == 0, invocation.output
    result = load_envelope(output)
    assert result.temperature == 77.0
    assert result.broadening.sigma == 150.0
    assert result.grid.de == 5.0


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
    modes = load_envelope(output).modes
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
    result = load_lines(output)
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
            "--temperature", "0", "--min-weight", "1e-6", "--max-lines", "500",
        ],
    )

    assert invocation.exit_code == 0, invocation.output
    result = load_lines(output)
    assert result.temperature == 0.0
    assert result.selection.min_weight == 1e-6
    assert result.selection.max_lines == 500
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
        ["lines", str(input_file), "-o", str(tmp_path / "out.json"), "--min-weight", "0"],
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


# --- plot による重ね描き ---


@pytest.fixture
def result_and_lines(tmp_path, input_file):
    """`run` と `lines` を同じ入力で走らせ、2 つの結果 JSON を返す。"""
    result = tmp_path / "result.json"
    lines = tmp_path / "lines.json"
    assert runner.invoke(app, ["run", str(input_file), "-o", str(result)]).exit_code == 0
    assert (
        runner.invoke(app, ["lines", str(input_file), "-o", str(lines)]).exit_code == 0
    )
    return result, lines


def test_plot_overlays_an_envelope_and_a_line_list(tmp_path, result_and_lines):
    result, lines = result_and_lines
    figure = tmp_path / "overlay.png"
    invocation = runner.invoke(
        app, ["plot", str(result), str(lines), "-o", str(figure)]
    )

    assert invocation.exit_code == 0, invocation.output
    assert figure.is_file()
    assert figure.stat().st_size > 0


def test_plot_overlay_ignores_the_order_of_the_two_files(tmp_path, result_and_lines):
    result, lines = result_and_lines
    figure = tmp_path / "overlay.png"
    invocation = runner.invoke(
        app, ["plot", str(lines), str(result), "-o", str(figure)]
    )

    assert invocation.exit_code == 0, invocation.output
    assert figure.is_file()


def test_plot_overlay_reports_lines_outside_the_energy_window(tmp_path, input_file):
    result = tmp_path / "result.json"
    lines = tmp_path / "lines.json"
    # E 窓を ZPL 周辺だけに絞れば、サイドバンドの線は窓の外に落ちる。
    runner.invoke(
        app, ["run", str(input_file), "-o", str(result), "--e-min", "-300", "--e-max", "300"]
    )
    runner.invoke(app, ["lines", str(input_file), "-o", str(lines)])

    invocation = runner.invoke(
        app, ["plot", str(result), str(lines), "-o", str(tmp_path / "overlay.png")]
    )

    assert invocation.exit_code == 0, invocation.output
    assert "outside the E window" in invocation.output


def test_plot_rejects_two_files_of_the_same_kind(tmp_path, result_and_lines):
    result, _ = result_and_lines
    invocation = runner.invoke(
        app, ["plot", str(result), str(result), "-o", str(tmp_path / "overlay.png")]
    )
    assert invocation.exit_code == 2


def test_plot_rejects_more_than_two_files(tmp_path, result_and_lines):
    result, lines = result_and_lines
    invocation = runner.invoke(
        app,
        ["plot", str(result), str(lines), str(lines), "-o", str(tmp_path / "overlay.png")],
    )
    assert invocation.exit_code == 2


def test_plot_overlay_accepts_a_magnification(tmp_path, result_and_lines):
    result, lines = result_and_lines
    figure = tmp_path / "overlay.png"
    invocation = runner.invoke(
        app, ["plot", str(result), str(lines), "-o", str(figure), "--magnify", "5"]
    )

    assert invocation.exit_code == 0, invocation.output
    assert figure.is_file()


def test_plot_overlay_bad_magnification_exits_with_one(tmp_path, result_and_lines):
    result, lines = result_and_lines
    invocation = runner.invoke(
        app,
        ["plot", str(result), str(lines), "-o", str(tmp_path / "x.png"), "--magnify", "0"],
    )
    assert invocation.exit_code == 1
    assert "error:" in invocation.output


def test_plot_rejects_magnification_without_an_overlay(tmp_path, result_and_lines):
    result, _ = result_and_lines
    invocation = runner.invoke(
        app, ["plot", str(result), "-o", str(tmp_path / "x.png"), "--magnify", "5"]
    )
    assert invocation.exit_code == 2


def test_lines_reads_the_selection_from_the_input_file(tmp_path, input_payload):
    """つまみは入力ファイルにも書ける。CLI は指定されたものだけを上書きする。"""
    input_payload["selection"] = {
        "min_weight": 1e-5,
        "max_lines": 4321,
        "max_quanta": 7,
    }
    path = tmp_path / "input.json"
    path.write_text(json.dumps(input_payload), encoding="utf-8")
    output = tmp_path / "lines.json"

    invocation = runner.invoke(
        app, ["lines", str(path), "-o", str(output), "--max-lines", "99"]
    )

    assert invocation.exit_code == 0, invocation.output
    selection = load_lines(output).selection
    assert selection.min_weight == 1e-5
    assert selection.max_lines == 99
    assert selection.max_quanta == 7
