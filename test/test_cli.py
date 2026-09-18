"""CLI の疎通と終了コード（合意文書 §9.1）。"""

from __future__ import annotations

import json

import numpy as np
import pytest
from typer.testing import CliRunner

from fcenvelope import load_envelope, load_lines, units
from fcenvelope.cli import app
from fcenvelope.emit import image_path_for, script_path_for

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
    assert result.system.modes[0].huang_rhys == 0.25


def test_run_writes_a_plot_script_by_default(tmp_path, input_file):
    """計算に添えて作図スクリプトが出る。図はそれを走らせて作る（ADR-0060）。"""
    output = tmp_path / "result.json"
    invocation = runner.invoke(app, ["run", str(input_file), "-o", str(output)])

    assert invocation.exit_code == 0, invocation.output
    script = script_path_for(output)
    assert script.is_file()
    assert str(script) in invocation.output


def test_run_keeps_an_edited_plot_script(tmp_path, input_file):
    """条件を振って計算をやり直しても、調整した図の設定は生き残る。"""
    output = tmp_path / "result.json"
    runner.invoke(app, ["run", str(input_file), "-o", str(output)])
    script = script_path_for(output)
    script.write_text("# 手で直した\n", encoding="utf-8")

    invocation = runner.invoke(
        app, ["run", str(input_file), "-o", str(output), "--sigma", "80"]
    )

    assert invocation.exit_code == 0, invocation.output
    assert script.read_text(encoding="utf-8") == "# 手で直した\n"
    assert f"kept {script}" in invocation.output


def test_force_script_regenerates_the_plot_script(tmp_path, input_file):
    output = tmp_path / "result.json"
    runner.invoke(app, ["run", str(input_file), "-o", str(output)])
    script = script_path_for(output)
    script.write_text("# 手で直した\n", encoding="utf-8")

    invocation = runner.invoke(
        app, ["run", str(input_file), "-o", str(output), "--force-script"]
    )

    assert invocation.exit_code == 0, invocation.output
    assert "def draw(" in script.read_text(encoding="utf-8")


def test_no_script_writes_nothing_but_the_result(tmp_path, input_file):
    """名前を変えながら掃引する実行のための逃げ道。"""
    output = tmp_path / "result.json"
    invocation = runner.invoke(
        app, ["run", str(input_file), "-o", str(output), "--no-script"]
    )

    assert invocation.exit_code == 0, invocation.output
    assert not script_path_for(output).exists()


def test_the_script_can_be_sent_somewhere_else(tmp_path, input_file):
    output = tmp_path / "result.json"
    elsewhere = tmp_path / "figures" / "mine.py"
    invocation = runner.invoke(
        app, ["run", str(input_file), "-o", str(output), "--script", str(elsewhere)]
    )

    assert invocation.exit_code == 0, invocation.output
    assert elsewhere.is_file()
    assert not script_path_for(output).exists()


def test_script_and_no_script_together_is_a_usage_error(tmp_path, input_file):
    invocation = runner.invoke(
        app,
        [
            "run", str(input_file), "-o", str(tmp_path / "result.json"),
            "--script", str(tmp_path / "mine.py"), "--no-script",
        ],
    )
    assert invocation.exit_code == 2


def test_run_overrides_the_conditions(tmp_path, input_file):
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
    restored = load_envelope(output)
    assert restored.temperature == 0.0
    assert restored.broadening.sigma == 80.0
    assert restored.grid.e_min == -6000.0
    assert restored.grid.e_max == 2000.0
    assert restored.grid.de == 4.0


def test_run_leaves_unspecified_fields_untouched(tmp_path, input_file):
    output = tmp_path / "result.json"
    invocation = runner.invoke(
        app, ["run", str(input_file), "-o", str(output), "--temperature", "77"]
    )

    assert invocation.exit_code == 0, invocation.output
    restored = load_envelope(output)
    assert restored.temperature == 77.0
    assert restored.broadening.sigma == 150.0
    assert restored.grid.de == 5.0


def test_overrides_are_read_in_the_units_of_the_input_file(tmp_path, input_file):
    """ファイルに書いてある値をそのまま CLI に移しても結果は変わらない（ADR-0050）。

    上書きは正準化の前に入力ファイルの型へ適用されるので、CLI の値は常にファイルと
    同じ単位・流儀で読まれる。
    """
    plain = tmp_path / "plain.json"
    restated = tmp_path / "restated.json"
    assert runner.invoke(app, ["run", str(input_file), "-o", str(plain)]).exit_code == 0
    invocation = runner.invoke(
        app,
        [
            "run", str(input_file), "-o", str(restated),
            "--temperature", "300", "--sigma", "150",
            "--e-min", "-4000", "--e-max", "1000", "--de", "5",
        ],
    )

    assert invocation.exit_code == 0, invocation.output
    first, second = load_envelope(plain), load_envelope(restated)
    assert first.temperature == second.temperature
    assert first.broadening == second.broadening
    assert first.grid == second.grid
    np.testing.assert_array_equal(first.density, second.density)


def test_sigma_is_overridden_in_the_broadening_unit(tmp_path, input_payload):
    """sigma を eV で書いたファイルでは --sigma も eV で読む（ADR-0050, 0053）。

    上書きは入力ファイルの型に当ててから正準化されるので、ファイルの broadening
    ブロックの単位がそのまま CLI の値の単位になる。cm^-1 と解釈されていれば、
    同じ数値を与えても sigma が桁違いにずれる。
    """
    in_ev = 150.0 / units.energy_conversion_factor("eV")
    input_payload["broadening"] = {"sigma": in_ev, "unit": "eV"}
    path = tmp_path / "input.json"
    path.write_text(json.dumps(input_payload), encoding="utf-8")

    output = tmp_path / "result.json"
    invocation = runner.invoke(
        app,
        ["run", str(path), "-o", str(output), "--sigma", str(2.0 * in_ev)],
    )

    assert invocation.exit_code == 0, invocation.output
    assert load_envelope(output).broadening.sigma == pytest.approx(300.0, rel=1e-12)


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
    modes = load_envelope(output).system.modes
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


def test_script_subcommand_regenerates_a_script_for_a_stored_result(tmp_path, input_file):
    output = tmp_path / "result.json"
    assert (
        runner.invoke(
            app, ["run", str(input_file), "-o", str(output), "--no-script"]
        ).exit_code
        == 0
    )

    script = tmp_path / "again.py"
    invocation = runner.invoke(app, ["script", str(output), "-o", str(script)])

    assert invocation.exit_code == 0, invocation.output
    assert "def draw(" in script.read_text(encoding="utf-8")


def test_script_subcommand_keeps_an_existing_file(tmp_path, input_file):
    output = tmp_path / "result.json"
    runner.invoke(app, ["run", str(input_file), "-o", str(output), "--no-script"])
    script = tmp_path / "again.py"
    script.write_text("# 手で直した\n", encoding="utf-8")

    kept = runner.invoke(app, ["script", str(output), "-o", str(script)])
    forced = runner.invoke(app, ["script", str(output), "-o", str(script), "--force"])

    assert kept.exit_code == 0 and f"kept {script}" in kept.output
    assert forced.exit_code == 0 and "def draw(" in script.read_text(encoding="utf-8")


def test_invalid_input_exits_with_one(tmp_path, input_payload):
    input_payload["frequency_unit"] = "nm"
    path = tmp_path / "input.json"
    path.write_text(json.dumps(input_payload), encoding="utf-8")

    invocation = runner.invoke(app, ["run", str(path), "-o", str(tmp_path / "out.json")])

    assert invocation.exit_code == 1
    assert "error:" in invocation.output
    assert "nm" in invocation.output


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
    assert result.system.modes[0].huang_rhys == 0.25
    assert result.lines[0].energy == 0.0


def test_lines_prints_the_strongest_transitions(tmp_path, input_file):
    output = tmp_path / "lines.json"
    invocation = runner.invoke(
        app, ["lines", str(input_file), "-o", str(output), "--top", "3"]
    )

    assert invocation.exit_code == 0, invocation.output
    assert "ZPL" in invocation.output
    assert "more" in invocation.output
    assert invocation.output.count("->") >= 1


def test_lines_top_zero_prints_no_table(tmp_path, input_file):
    output = tmp_path / "lines.json"
    invocation = runner.invoke(
        app, ["lines", str(input_file), "-o", str(output), "--top", "0"]
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


def test_lines_writes_a_plot_script_by_default(tmp_path, input_file):
    output = tmp_path / "lines.json"
    invocation = runner.invoke(
        app, ["lines", str(input_file), "-o", str(output), "--top", "0"]
    )

    assert invocation.exit_code == 0, invocation.output
    assert script_path_for(output).is_file()


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


# --- script による重ね描き ---


@pytest.fixture
def result_and_lines(tmp_path, input_file):
    """`run` と `lines` を同じ入力で走らせ、2 つの結果 JSON を返す。"""
    result = tmp_path / "result.json"
    lines = tmp_path / "lines.json"
    assert runner.invoke(app, ["run", str(input_file), "-o", str(result)]).exit_code == 0
    assert (
        runner.invoke(
            app, ["lines", str(input_file), "-o", str(lines), "--top", "0"]
        ).exit_code
        == 0
    )
    return result, lines


def test_script_writes_an_overlay_for_an_envelope_and_a_line_list(
    tmp_path, result_and_lines
):
    result, lines = result_and_lines
    script = tmp_path / "overlay_plot.py"
    invocation = runner.invoke(
        app, ["script", str(result), str(lines), "-o", str(script)]
    )

    assert invocation.exit_code == 0, invocation.output
    text = script.read_text(encoding="utf-8")
    assert "MAGNIFY" in text and str(image_path_for(script).name) in text


def test_script_overlay_ignores_the_order_of_the_two_files(tmp_path, result_and_lines):
    result, lines = result_and_lines
    script = tmp_path / "overlay_plot.py"
    invocation = runner.invoke(
        app, ["script", str(lines), str(result), "-o", str(script)]
    )

    assert invocation.exit_code == 0, invocation.output
    text = script.read_text(encoding="utf-8")
    assert f"ENVELOPE = Path(__file__).parent / {result.name!r}" in text
    assert f"LINES = Path(__file__).parent / {lines.name!r}" in text


def test_script_rejects_two_files_of_the_same_kind(tmp_path, result_and_lines):
    result, _ = result_and_lines
    invocation = runner.invoke(
        app, ["script", str(result), str(result), "-o", str(tmp_path / "overlay.py")]
    )
    assert invocation.exit_code == 2


def test_script_rejects_more_than_two_files(tmp_path, result_and_lines):
    result, lines = result_and_lines
    invocation = runner.invoke(
        app,
        ["script", str(result), str(lines), str(lines), "-o", str(tmp_path / "x.py")],
    )
    assert invocation.exit_code == 2
