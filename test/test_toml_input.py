"""入力ファイルの書式（ADR-0069）。

TOML と JSON のどちらで書いても読んだ後は同じで、以降の扱いが変わらないことを見る。
書式を知っているのは `INPUT_FORMATS` の振り分けだけなので、検証・正準化の側のテストは
`test_validation.py` にあるものをそのまま使い回せる。
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from fcenvelope import FCEnvelopeInput, load_envelope
from fcenvelope.cli import app
from fcenvelope.errors import InvalidInputError, SchemaVersionError
from fcenvelope.inputs import INPUT_FORMATS

runner = CliRunner()

#: `conftest.input_payload` と同じ内容を TOML で書いたもの。
TOML_INPUT = """\
schema_version = 3
frequency_unit = "cm^-1"
coupling_convention = "g"
temperature = 300.0

[[modes]]
frequency = 1200.0
coupling = 0.5

[[modes]]
frequency = 450.0
coupling = 0.8

[broadening]
sigma = 150.0

[grid]
e_min = -4500.0
e_max = 1000.0

[grid.points]
de = 4.0
"""


@pytest.fixture
def toml_file(tmp_path):
    path = tmp_path / "input.toml"
    path.write_text(TOML_INPUT, encoding="utf-8")
    return path


def test_from_toml_reads_text():
    parsed = FCEnvelopeInput.from_toml(TOML_INPUT)

    assert [mode.frequency for mode in parsed.modes] == [1200.0, 450.0]
    assert parsed.to_system().modes[0].huang_rhys == 0.25


def test_from_toml_accepts_bytes():
    parsed = FCEnvelopeInput.from_toml(TOML_INPUT.encode("utf-8"))

    assert parsed.temperature == 300.0


def test_from_path_reads_toml_by_its_extension(toml_file, input_payload):
    """拡張子で書式が決まり、同じ内容なら JSON と一致する。"""
    from_toml = FCEnvelopeInput.from_path(toml_file)
    from_json = FCEnvelopeInput.from_obj(input_payload)

    assert from_toml.to_json() == from_json.to_json()


def test_toml_comments_are_allowed(tmp_path):
    """コメントが書けることは TOML を選んだ理由そのものである（ADR-0069）。"""
    path = tmp_path / "input.toml"
    path.write_text(
        "# 外部プログラムの出力から書き起こした\n"
        + TOML_INPUT.replace('coupling = 0.5', 'coupling = 0.5   # g'),
        encoding="utf-8",
    )

    assert FCEnvelopeInput.from_path(path).modes[0].coupling == 0.5


def test_modes_can_reference_a_csv_relative_to_the_toml_file(tmp_path):
    """CSV 参照の基準は書式によらず入力ファイルの位置（ADR-0019, 0069）。"""
    (tmp_path / "modes.csv").write_text(
        "frequency,coupling\n1200.0,0.5\n450.0,0.8\n", encoding="utf-8"
    )
    path = tmp_path / "input.toml"
    body = TOML_INPUT.replace(
        """[[modes]]
frequency = 1200.0
coupling = 0.5

[[modes]]
frequency = 450.0
coupling = 0.8

""",
        'modes = { path = "modes.csv" }\n\n',
    )
    path.write_text(body, encoding="utf-8")

    parsed = FCEnvelopeInput.from_path(path)

    assert [mode.frequency for mode in parsed.modes] == [1200.0, 450.0]


def test_malformed_toml_is_reported_as_an_input_error():
    with pytest.raises(InvalidInputError, match="invalid TOML"):
        FCEnvelopeInput.from_toml("temperature = ")


def test_an_unknown_extension_stops_before_reading(tmp_path):
    """中身は見ない。拡張子が分からなければその場で止める（ADR-0069）。"""
    path = tmp_path / "input.yaml"
    path.write_text(TOML_INPUT, encoding="utf-8")

    with pytest.raises(InvalidInputError) as caught:
        FCEnvelopeInput.from_path(path)

    message = str(caught.value)
    assert ".yaml" in message
    for suffix in INPUT_FORMATS:
        assert suffix in message


def test_a_toml_file_still_carries_the_schema_version(tmp_path):
    """版の検査は書式の手前ではなく入力ファイルの型にある。"""
    path = tmp_path / "input.toml"
    path.write_text(TOML_INPUT.replace("schema_version = 3", "schema_version = 1"), encoding="utf-8")

    with pytest.raises(SchemaVersionError):
        FCEnvelopeInput.from_path(path)


def test_run_accepts_a_toml_input(tmp_path, toml_file):
    output = tmp_path / "result.json"
    invocation = runner.invoke(app, ["run", str(toml_file), "-o", str(output)])

    assert invocation.exit_code == 0, invocation.output
    assert load_envelope(output).temperature == 300.0


def test_the_default_output_name_drops_the_toml_extension(toml_file):
    """既定の出力名は入力の拡張子を除いた部分から作る（ADR-0063）。"""
    invocation = runner.invoke(app, ["run", str(toml_file)])

    assert invocation.exit_code == 0, invocation.output
    assert (toml_file.parent / "input_envelope.json").is_file()


def test_the_effective_settings_of_a_toml_run_are_json(tmp_path, toml_file):
    """実効設定は入力が TOML でも JSON で書き出し、そのまま読み返せる（ADR-0065, 0069）。"""
    output = tmp_path / "result.json"
    runner.invoke(app, ["run", str(toml_file), "-o", str(output)])
    config = tmp_path / "result_config.json"

    assert config.is_file()
    # TOML では書けない `null` が埋まっている。JSON を残す理由そのもの。
    assert json.loads(config.read_text(encoding="utf-8"))["selection"]["max_quanta"] is None

    again = tmp_path / "again.json"
    invocation = runner.invoke(app, ["run", str(config), "-o", str(again)])

    assert invocation.exit_code == 0, invocation.output
    assert load_envelope(again).temperature == 300.0


def test_an_override_value_is_json_even_for_a_toml_input(tmp_path, toml_file):
    """TOML に `null` はないので、「無し」を渡せるのは `--override` だけ（ADR-0064, 0069）。"""
    output = tmp_path / "lines.json"
    invocation = runner.invoke(
        app,
        ["lines", str(toml_file), "-o", str(output), "--override", "selection.max_quanta=null"],
    )

    assert invocation.exit_code == 0, invocation.output
    config = json.loads((tmp_path / "lines_config.json").read_text(encoding="utf-8"))
    assert config["selection"]["max_quanta"] is None
