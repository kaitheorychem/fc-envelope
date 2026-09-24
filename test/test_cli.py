"""CLI の疎通と終了コード（合意文書 §9.1）。"""

from __future__ import annotations

import copy
import json
import warnings
from pathlib import Path

import numpy as np
import pytest
from conftest import run_script
from typer.testing import CliRunner

from fcenvelope import load_envelope, load_lines, units
from fcenvelope.cli import app
from fcenvelope.emit import image_path_for, script_path_for
from fcenvelope.inputs import template_text
from fcenvelope.errors import NumericalQualityWarning

runner = CliRunner()


@pytest.fixture
def input_file(tmp_path, input_payload):
    path = tmp_path / "input.json"
    path.write_text(json.dumps(input_payload), encoding="utf-8")
    return path


@pytest.fixture
def warning_input_file(tmp_path, input_payload):
    """品質の警告がちょうど 1 つ出る入力。

    全域グリッドは `de` を 2 の冪へ切り上げて作られるので、窓が同じでも `de` で
    覆う幅が変わる（ADR-0070）。この窓では `de = 5.0` だと全域幅が 10240 に留まり、
    端の折り返しが閾値を超える。警告の**見せ方**を見るためのものなので、警告が出る
    条件をここに持たせる。文書に載る例の側は警告の出ない値にしてある。
    """
    payload = copy.deepcopy(input_payload)
    payload["grid"] = {"e_min": -4000.0, "e_max": 1000.0, "points": {"de": 5.0}}
    path = tmp_path / "warns.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
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
        app,
        ["run", str(input_file), "-o", str(output), "--override", "broadening.sigma=80"],
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
    """つまみは `--override` 1 つで、キーは入力ファイル中の位置である（ADR-0064）。"""
    output = tmp_path / "result.json"
    invocation = runner.invoke(
        app,
        [
            "run", str(input_file), "-o", str(output),
            "--override", "temperature=0",
            "--override", "broadening.sigma=80",
            "--override", "grid.e_min=-6000",
            "--override", "grid.e_max=2000",
            "--override", "grid.points.de=4",
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
        app, ["run", str(input_file), "-o", str(output), "--override", "temperature=77"]
    )

    assert invocation.exit_code == 0, invocation.output
    restored = load_envelope(output)
    assert restored.temperature == 77.0
    assert restored.broadening.sigma == 150.0
    assert restored.grid.de == 4.0


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
            "--override", "temperature=300", "--override", "broadening.sigma=150",
            "--override", "grid.e_min=-4500", "--override", "grid.e_max=1000",
            "--override", "grid.points.de=4",
        ],
    )

    assert invocation.exit_code == 0, invocation.output
    first, second = load_envelope(plain), load_envelope(restated)
    assert first.temperature == second.temperature
    assert first.broadening == second.broadening
    assert first.grid == second.grid
    np.testing.assert_array_equal(first.density, second.density)


def test_sigma_is_overridden_in_the_broadening_unit(tmp_path, input_payload):
    """sigma を eV で書いたファイルでは上書きの値も eV で読む（ADR-0050, 0053）。

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
        [
            "run", str(path), "-o", str(output),
            "--override", f"broadening.sigma={2.0 * in_ev}",
        ],
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
        app,
        [
            "run", str(input_file), "-o", str(tmp_path / "out.json"),
            "--override", "grid.e_min=5000",
        ],
    )
    assert invocation.exit_code == 1
    assert "error:" in invocation.output


def test_a_misspelled_override_key_exits_with_one(tmp_path, input_file):
    """誤字は黙って無視されず、未知のフィールドとして弾かれる（ADR-0064, 0065）。"""
    invocation = runner.invoke(
        app,
        [
            "run", str(input_file), "-o", str(tmp_path / "out.json"),
            "--override", "grid.points.dee=4",
        ],
    )
    assert invocation.exit_code == 1
    assert "dee" in invocation.output


def test_modes_cannot_be_overridden(tmp_path, input_file):
    """モードは分子固有のデータなので上書き対象にしない（ADR-0012）。"""
    invocation = runner.invoke(
        app,
        [
            "run", str(input_file), "-o", str(tmp_path / "out.json"),
            "--override", "modes=[]",
        ],
    )
    assert invocation.exit_code == 2
    assert "modes" in invocation.output


@pytest.mark.parametrize("item", ["oops", "=4", "grid..de=4", "temperature.x=1"])
def test_a_malformed_override_is_a_usage_error(tmp_path, input_file, item):
    """書式そのものの誤りだけが使用法エラーで、値の正しさは入力の検証に任せる。"""
    invocation = runner.invoke(
        app,
        ["run", str(input_file), "-o", str(tmp_path / "out.json"), "--override", item],
    )
    assert invocation.exit_code == 2


def test_an_override_value_is_read_as_json(tmp_path, input_file):
    """`null` も数も文字列も同じ規則で通る（ADR-0064）。"""
    output = tmp_path / "lines.json"
    invocation = runner.invoke(
        app,
        [
            "lines", str(input_file), "-o", str(output), "--top", "0",
            "--override", "selection.max_quanta=null",
            "--override", "selection.max_lines=500",
            "--override", "frequency_unit=cm^-1",
        ],
    )

    assert invocation.exit_code == 0, invocation.output
    restored = load_lines(output)
    assert restored.selection.max_quanta is None
    assert restored.selection.max_lines == 500


# --- 品質の警告の見せ方（ADR-0009） ---


@pytest.mark.parametrize("command", ["run", "lines"])
def test_a_quality_warning_is_shown_once_in_the_cli_s_own_form(
    tmp_path, warning_input_file, command
):
    """同じ文言が 2 度、片方は実装のファイル名と行番号つきで出ることのないように。

    `report_quality` は `warnings.warn` でも発報するが、CLI は結果の診断値から
    自分の書式で出す。利用者に見せる形は 1 つに決める（ADR-0068）。閾値を割る
    のは `run` だけなので、`lines` では 1 度も出ないことを見る。
    """
    output = tmp_path / "result.json"
    expected = 1 if command == "run" else 0

    with warnings.catch_warnings(record=True) as raised:
        warnings.simplefilter("always")
        invocation = runner.invoke(
            app, [command, str(warning_input_file), "-o", str(output)]
        )

    assert invocation.exit_code == 0, invocation.output
    assert not [w for w in raised if issubclass(w.category, NumericalQualityWarning)]
    assert invocation.output.count("edge_intensity_ratio") == expected
    assert invocation.output.count("cli.py:") == 0


def test_a_quality_warning_still_reaches_the_log(tmp_path, warning_input_file):
    """表示を 1 つに絞っても、ログと診断値の経路は塞がない。"""
    output, log = tmp_path / "result.json", tmp_path / "run.log"

    invocation = runner.invoke(
        app, ["run", str(warning_input_file), "-o", str(output), "--log", str(log)]
    )

    assert invocation.exit_code == 0, invocation.output
    assert "edge_intensity_ratio" in log.read_text(encoding="utf-8")
    assert any("edge_intensity_ratio" in m for m in load_envelope(output).diagnostics.messages)


# --- 既定の出力名（ADR-0063） ---


def test_run_names_its_output_after_the_input(tmp_path, input_file):
    invocation = runner.invoke(app, ["run", str(input_file)])

    assert invocation.exit_code == 0, invocation.output
    output = tmp_path / "input_envelope.json"
    assert load_envelope(output).energy.size > 0
    assert script_path_for(output).is_file()


def test_lines_names_its_output_after_the_input(tmp_path, input_file):
    invocation = runner.invoke(app, ["lines", str(input_file), "--top", "0"])

    assert invocation.exit_code == 0, invocation.output
    assert load_lines(tmp_path / "input_lines.json").diagnostics.n_lines > 0


def test_the_default_output_never_touches_the_input(tmp_path, input_file):
    """種類の接尾辞は、入力を踏み潰す道と run/lines の衝突を同時に塞ぐ（ADR-0063）。"""
    before = input_file.read_text(encoding="utf-8")
    assert runner.invoke(app, ["run", str(input_file)]).exit_code == 0
    assert runner.invoke(app, ["lines", str(input_file), "--top", "0"]).exit_code == 0

    assert input_file.read_text(encoding="utf-8") == before
    assert (tmp_path / "input_envelope.json").is_file()
    assert (tmp_path / "input_lines.json").is_file()


def test_the_default_output_goes_next_to_the_input(tmp_path, input_payload, monkeypatch):
    """カレントディレクトリではなく入力ファイルの隣に置く（ADR-0063）。"""
    elsewhere = tmp_path / "inputs"
    elsewhere.mkdir()
    path = elsewhere / "input.json"
    path.write_text(json.dumps(input_payload), encoding="utf-8")
    here = tmp_path / "cwd"
    here.mkdir()
    monkeypatch.chdir(here)

    invocation = runner.invoke(app, ["run", str(path)])

    assert invocation.exit_code == 0, invocation.output
    assert (elsewhere / "input_envelope.json").is_file()
    assert list(here.iterdir()) == []


def _generate_everything(
    input_path, *, run_output=None, lines_output=None
) -> dict[str, bytes]:
    """1 つの入力から作れるファイルを全部作り、新しくできたものの名前と中身を返す。

    結果・実効設定・作図スクリプトに加えて、失敗時の痕跡のログと、スクリプトを
    走らせてできる画像まで作る。名前の規則を関数ごとに信じるのではなく、実際に
    ディレクトリに現れたものを数える。
    """
    folder = input_path.parent
    before = {path.name for path in folder.iterdir()}

    def target(output):
        return [] if output is None else ["-o", str(output)]

    failing = [
        ["run", str(input_path), *target(run_output), "--override", "grid.e_min=5000"],
        ["lines", str(input_path), *target(lines_output),
         "--override", "selection.min_weight=0"],
    ]
    for arguments in failing:
        assert runner.invoke(app, arguments).exit_code == 1
    succeeding = [
        ["run", str(input_path), *target(run_output)],
        ["lines", str(input_path), *target(lines_output), "--top", "0"],
    ]
    for arguments in succeeding:
        invocation = runner.invoke(app, arguments)
        assert invocation.exit_code == 0, invocation.output

    created = sorted(set(path.name for path in folder.iterdir()) - before)
    for name in created:
        if name.endswith(".py"):
            finished = run_script(folder / name)
            assert finished.returncode == 0, finished.stderr.decode()

    return {
        path.name: path.read_bytes()
        for path in folder.iterdir()
        if path.name not in before
    }


def test_two_inputs_in_one_folder_never_write_the_same_file(tmp_path, input_payload):
    """既定の名前はどれも入力の名前を継ぐので、隣の入力の結果を上書きしない（ADR-0063）。

    固定名のファイルが 1 つでも生まれると、同じディレクトリで 2 つ目の入力を流した
    ときに黙って潰される。生成物の種類を増やしたときにそれを入れないための見張り。
    """
    alpha = tmp_path / "alpha.json"
    beta = tmp_path / "beta.json"
    for path in (alpha, beta):
        path.write_text(json.dumps(input_payload), encoding="utf-8")

    from_alpha = _generate_everything(alpha)
    from_beta = _generate_everything(beta)

    kinds = {".json", ".py", ".png", ".log"}
    assert {Path(name).suffix for name in from_alpha} == kinds
    assert all("alpha" in name for name in from_alpha), sorted(from_alpha)
    assert all("beta" in name for name in from_beta), sorted(from_beta)
    assert len(from_beta) == len(from_alpha)
    for name, content in from_alpha.items():
        assert (tmp_path / name).read_bytes() == content, name


def test_every_derived_name_follows_the_output_name(tmp_path, input_file):
    """`-o` を書けば、そこから先の名前は入力ではなく `-o` の名前を継ぐ（ADR-0060, 0063）。

    温度を振って `-o T100.json` … と書く掃引で、添えるファイルが点ごとに分かれる
    ことを確かめる。
    """
    created = _generate_everything(
        input_file,
        run_output=tmp_path / "T100.json",
        lines_output=tmp_path / "L100.json",
    )

    kinds = {".json", ".py", ".png", ".log"}
    assert {Path(name).suffix for name in created} == kinds
    envelope = [name for name in created if "T100" in name]
    lines = [name for name in created if "L100" in name]
    assert sorted(envelope + lines) == sorted(created)
    assert len(envelope) == len(lines)


# --- 実効設定の書き出し（ADR-0065） ---


def test_run_writes_the_effective_settings(tmp_path, input_file):
    output = tmp_path / "result.json"
    invocation = runner.invoke(
        app,
        ["run", str(input_file), "-o", str(output), "--override", "temperature=77"],
    )

    assert invocation.exit_code == 0, invocation.output
    config = tmp_path / "result_config.json"
    assert str(config) in invocation.output
    written = json.loads(config.read_text(encoding="utf-8"))
    # 上書き後の値、既定値で埋まった項目、書いたとおりの単位・流儀。
    assert written["temperature"] == 77.0
    assert written["selection"]["min_weight"] == 0.0001
    assert written["coupling_convention"] == "g"
    assert written["broadening"] == {"sigma": 150.0, "unit": "cm^-1"}


def test_the_effective_settings_reproduce_the_run(tmp_path, input_file):
    """書き出した設定をそのまま与えれば同じ計算になる（ADR-0065）。"""
    first = tmp_path / "first.json"
    assert (
        runner.invoke(
            app,
            [
                "run", str(input_file), "-o", str(first), "--no-script",
                "--override", "temperature=77", "--override", "grid.points.de=4",
            ],
        ).exit_code
        == 0
    )

    second = tmp_path / "second.json"
    invocation = runner.invoke(
        app,
        ["run", str(tmp_path / "first_config.json"), "-o", str(second), "--no-script"],
    )

    assert invocation.exit_code == 0, invocation.output
    before, after = load_envelope(first), load_envelope(second)
    assert (before.temperature, before.grid, before.broadening) == (
        after.temperature, after.grid, after.broadening,
    )
    assert before.system.modes == after.system.modes
    np.testing.assert_array_equal(before.density, after.density)


def test_the_effective_settings_are_written_before_the_computation(tmp_path, input_file):
    """値の誤りで止まった実行でも、何が使われるはずだったかは残る（ADR-0065）。"""
    output = tmp_path / "result.json"
    invocation = runner.invoke(
        app,
        [
            "run", str(input_file), "-o", str(output),
            "--override", "grid.e_min=5000",
        ],
    )

    assert invocation.exit_code == 1
    assert not output.exists()
    written = json.loads((tmp_path / "result_config.json").read_text(encoding="utf-8"))
    assert written["grid"]["e_min"] == 5000.0


def test_the_effective_settings_are_always_refreshed(tmp_path, input_file):
    """作図スクリプトと違って残さない。古いものを残すと名目が嘘になる（ADR-0065）。"""
    output = tmp_path / "result.json"
    config = tmp_path / "result_config.json"
    config.write_text("# 古い設定\n", encoding="utf-8")

    invocation = runner.invoke(app, ["run", str(input_file), "-o", str(output)])

    assert invocation.exit_code == 0, invocation.output
    assert json.loads(config.read_text(encoding="utf-8"))["temperature"] == 300.0


def test_the_effective_settings_can_be_sent_somewhere_else(tmp_path, input_file):
    output = tmp_path / "result.json"
    elsewhere = tmp_path / "settings" / "mine.json"
    invocation = runner.invoke(
        app, ["run", str(input_file), "-o", str(output), "--config", str(elsewhere)]
    )

    assert invocation.exit_code == 0, invocation.output
    assert elsewhere.is_file()
    assert not (tmp_path / "result_config.json").exists()


def test_no_config_writes_nothing_but_the_result(tmp_path, input_file):
    output = tmp_path / "result.json"
    invocation = runner.invoke(
        app, ["run", str(input_file), "-o", str(output), "--no-config"]
    )

    assert invocation.exit_code == 0, invocation.output
    assert not (tmp_path / "result_config.json").exists()


def test_config_and_no_config_together_is_a_usage_error(tmp_path, input_file):
    invocation = runner.invoke(
        app,
        [
            "run", str(input_file), "-o", str(tmp_path / "result.json"),
            "--config", str(tmp_path / "mine.json"), "--no-config",
        ],
    )
    assert invocation.exit_code == 2


def test_lines_writes_the_effective_settings_too(tmp_path, input_file):
    output = tmp_path / "lines.json"
    invocation = runner.invoke(
        app, ["lines", str(input_file), "-o", str(output), "--top", "0"]
    )

    assert invocation.exit_code == 0, invocation.output
    written = json.loads((tmp_path / "lines_config.json").read_text(encoding="utf-8"))
    assert written["selection"]["max_lines"] == 10000


def test_the_effective_settings_inline_modes_read_from_csv(tmp_path, input_payload):
    """CSV が後で変わっても、書き出した設定だけで再現できる（ADR-0065）。"""
    (tmp_path / "modes.csv").write_text(
        "frequency,coupling\n1200.0,0.5\n", encoding="utf-8"
    )
    input_payload["modes"] = {"path": "modes.csv"}
    path = tmp_path / "input.json"
    path.write_text(json.dumps(input_payload), encoding="utf-8")

    invocation = runner.invoke(app, ["run", str(path), "--no-script"])

    assert invocation.exit_code == 0, invocation.output
    written = json.loads(
        (tmp_path / "input_envelope_config.json").read_text(encoding="utf-8")
    )
    assert written["modes"] == [{"frequency": 1200.0, "coupling": 0.5}]


def test_missing_input_file_exits_with_one(tmp_path):
    invocation = runner.invoke(
        app, ["run", str(tmp_path / "absent.json"), "-o", str(tmp_path / "out.json")]
    )
    assert invocation.exit_code == 1


def test_usage_error_exits_with_two():
    """入力ファイルは省略できない。`-o` は省略できる（ADR-0063）。"""
    assert runner.invoke(app, ["run"]).exit_code == 2


def test_unknown_command_exits_with_two():
    assert runner.invoke(app, ["nope"]).exit_code == 2


def test_help_and_version():
    assert runner.invoke(app, ["--help"]).exit_code == 0
    version = runner.invoke(app, ["--version"])
    assert version.exit_code == 0
    assert version.output.strip()


# --- template サブコマンド ---


def test_template_goes_to_standard_output(tmp_path):
    """`-o` がなければ端末に出る。そのまま見て書き方を確かめられる（ADR-0074）。"""
    invocation = runner.invoke(app, ["template"])

    assert invocation.exit_code == 0, invocation.output
    assert invocation.output == template_text()


def test_the_written_template_runs(tmp_path):
    """書き出した雛形が、そのまま `run` に渡せること。"""
    path = tmp_path / "input.toml"
    written = runner.invoke(app, ["template", "-o", str(path)])

    assert written.exit_code == 0, written.output
    assert f"wrote {path}" in written.output

    invocation = runner.invoke(app, ["run", str(path)])

    assert invocation.exit_code == 0, invocation.output
    assert load_envelope(path.with_name("input_envelope.json")).energy.size > 0


def test_template_keeps_an_existing_input_file(tmp_path):
    """既にある入力ファイルは黙って潰さない（作図スクリプトと同じ扱い、ADR-0060）。"""
    path = tmp_path / "input.toml"
    path.write_text("# 書きかけ\n", encoding="utf-8")

    invocation = runner.invoke(app, ["template", "-o", str(path)])

    assert invocation.exit_code == 0, invocation.output
    assert path.read_text(encoding="utf-8") == "# 書きかけ\n"
    assert f"kept {path}" in invocation.output


def test_force_overwrites_an_existing_input_file(tmp_path):
    path = tmp_path / "input.toml"
    path.write_text("# 書きかけ\n", encoding="utf-8")

    invocation = runner.invoke(app, ["template", "-o", str(path), "--force"])

    assert invocation.exit_code == 0, invocation.output
    assert path.read_text(encoding="utf-8") == template_text()


def test_the_template_cannot_be_written_as_json(tmp_path):
    """雛形はコメントが本体なので TOML だけである（ADR-0074）。"""
    path = tmp_path / "input.json"

    invocation = runner.invoke(app, ["template", "-o", str(path)])

    assert invocation.exit_code == 2
    assert not path.exists()


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
            "--override", "temperature=0", "--override", "selection.min_weight=1e-6",
            "--override", "selection.max_lines=500",
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
        [
            "lines", str(input_file), "-o", str(tmp_path / "out.json"),
            "--override", "selection.min_weight=0",
        ],
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


def test_an_override_may_carry_its_own_unit(tmp_path, input_payload):
    """上書きの値にも `[値, "単位"]` を渡せること（ADR-0064, 0072）。

    上書きの値は書式によらず JSON として読むので、組はそのまま通る。単位を変える
    のに値と `unit` を 2 回に分けて上書きする必要がない。
    """
    path = tmp_path / "input.json"
    path.write_text(json.dumps(input_payload), encoding="utf-8")
    in_ev = 300.0 / units.energy_conversion_factor("eV")

    output = tmp_path / "result.json"
    invocation = runner.invoke(
        app,
        [
            "run", str(path), "-o", str(output),
            "--override", f'broadening.sigma=[{in_ev}, "eV"]',
        ],
    )

    assert invocation.exit_code == 0, invocation.output
    assert load_envelope(output).broadening.sigma == pytest.approx(300.0, rel=1e-12)


def test_an_override_may_use_an_alias(tmp_path, input_payload):
    """上書きの値の単位にも別名 `a.u.` が使えること（ADR-0076）。"""
    path = tmp_path / "input.json"
    path.write_text(json.dumps(input_payload), encoding="utf-8")
    in_au = 300.0 / units.energy_conversion_factor("hartree")

    output = tmp_path / "result.json"
    invocation = runner.invoke(
        app,
        [
            "run", str(path), "-o", str(output),
            "--override", f'broadening.sigma=[{in_au}, "a.u."]',
        ],
    )

    assert invocation.exit_code == 0, invocation.output
    assert load_envelope(output).broadening.sigma == pytest.approx(300.0, rel=1e-12)
