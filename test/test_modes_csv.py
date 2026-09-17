"""モード表 CSV の読み込み（合意文書 modes-csv-20260915）。"""

from __future__ import annotations

import copy
import json

import pytest

from fcenvelope import FCEnvelopeInput, InvalidInputError, ModeSpec, VibrationalMode
from fcenvelope.inputs import read_mode_specs_csv


def _write(path, text: str):
    path.write_text(text, encoding="utf-8")
    return path


def test_reads_modes_by_column_name(tmp_path):
    path = _write(tmp_path / "modes.csv", "frequency,coupling\n1200.0,0.5\n450.0,0.8\n")
    assert read_mode_specs_csv(path) == [
        ModeSpec(frequency=1200.0, coupling=0.5),
        ModeSpec(frequency=450.0, coupling=0.8),
    ]


def test_column_order_is_free(tmp_path):
    path = _write(tmp_path / "modes.csv", "coupling,frequency\n0.5,1200.0\n0.8,450.0\n")
    assert read_mode_specs_csv(path) == [
        ModeSpec(frequency=1200.0, coupling=0.5),
        ModeSpec(frequency=450.0, coupling=0.8),
    ]


def test_rfc4180_quoting_crlf_and_missing_final_newline(tmp_path):
    path = tmp_path / "modes.csv"
    path.write_bytes(b'"frequency",coupling\r\n"1200.0",0.5\r\n450.0,"0.8"')
    assert read_mode_specs_csv(path) == [
        ModeSpec(frequency=1200.0, coupling=0.5),
        ModeSpec(frequency=450.0, coupling=0.8),
    ]


def test_utf8_bom_is_tolerated(tmp_path):
    path = tmp_path / "modes.csv"
    path.write_bytes(b"\xef\xbb\xbffrequency,coupling\n1200.0,0.5\n")
    assert read_mode_specs_csv(path) == [ModeSpec(frequency=1200.0, coupling=0.5)]


def test_header_is_optional(tmp_path):
    path = _write(tmp_path / "modes.csv", "1200.0,0.5\n450.0,0.8\n")
    assert read_mode_specs_csv(path) == [
        ModeSpec(frequency=1200.0, coupling=0.5),
        ModeSpec(frequency=450.0, coupling=0.8),
    ]


def test_headerless_single_row_without_final_newline(tmp_path):
    path = tmp_path / "modes.csv"
    path.write_bytes(b'"1200.0",0.5')
    assert read_mode_specs_csv(path) == [ModeSpec(frequency=1200.0, coupling=0.5)]


@pytest.mark.parametrize(
    "text",
    [
        "frequency\n1200.0\n",
        "freq,coupling\n1200.0,0.5\n",
        "frequency, coupling\n1200.0,0.5\n",
        "frequency,frequency\n1200.0,0.5\n",
        "index,frequency,coupling\n1,1200.0,0.5\n",
        "frequency,coupling,label\n1200.0,0.5,a\n",
        "# comment\nfrequency,coupling\n1200.0,0.5\n",
    ],
)
def test_first_line_that_is_neither_header_nor_mode(tmp_path, text):
    path = _write(tmp_path / "modes.csv", text)
    with pytest.raises(InvalidInputError) as excinfo:
        read_mode_specs_csv(path)
    message = str(excinfo.value)
    assert "modes.csv:1:" in message
    assert "a header, if present, must consist of exactly" in message


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("frequency,coupling\n1200.0,0.5\n450.0\n", "modes.csv:3: expected 2 fields, got 1"),
        ("frequency,coupling\n1200.0,0.5\nabc,0.8\n", "modes.csv:3"),
        ("1200.0,0.5\n1,2,3\n", "modes.csv:2: expected 2 fields, got 3"),
        ("frequency,coupling\n# comment\n1200.0,0.5\n", "modes.csv:2: expected 2 fields, got 1"),
        ("frequency,coupling\n\n1200.0,0.5\n", "blank lines are not allowed"),
        ("frequency,coupling\n1200.0,0.5\n\n", "modes.csv:3"),
        ('frequency,coupling\n"12"00.0,0.5\n', "malformed CSV"),
        ("frequency,coupling\n", "no mode rows"),
        ("", "modes file is empty"),
    ],
)
def test_malformed_csv_reports_the_location(tmp_path, text, fragment):
    path = _write(tmp_path / "modes.csv", text)
    with pytest.raises(InvalidInputError) as excinfo:
        read_mode_specs_csv(path)
    message = str(excinfo.value)
    assert fragment in message
    assert "a header, if present" not in message


def test_missing_modes_file(tmp_path):
    with pytest.raises(InvalidInputError):
        read_mode_specs_csv(tmp_path / "absent.csv")


def test_input_json_references_csv_relative_to_itself(tmp_path, input_payload, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write(data_dir / "modes.csv", "frequency,coupling\n1200.0,0.5\n450.0,0.8\n")
    payload = copy.deepcopy(input_payload)
    payload["modes"] = {"path": "modes.csv"}
    input_path = _write(data_dir / "input.json", json.dumps(payload))
    monkeypatch.chdir(tmp_path)  # カレントディレクトリではなく入力ファイル基準で解決される

    from_csv = FCEnvelopeInput.from_path(input_path)
    inline = FCEnvelopeInput.from_obj(input_payload)
    assert from_csv == inline
    assert from_csv.to_system().modes[0] == VibrationalMode(
        frequency=1200.0, huang_rhys=0.25
    )


def test_from_obj_resolves_against_base_dir(tmp_path, input_payload):
    _write(tmp_path / "modes.csv", "frequency,coupling\n1200.0,0.5\n")
    payload = copy.deepcopy(input_payload)
    payload["modes"] = {"path": "modes.csv"}
    parsed = FCEnvelopeInput.from_obj(payload, base_dir=tmp_path)
    assert parsed.modes == [ModeSpec(frequency=1200.0, coupling=0.5)]


def test_absolute_path_ignores_base_dir(tmp_path, input_payload):
    modes_path = _write(tmp_path / "modes.csv", "frequency,coupling\n1200.0,0.5\n")
    payload = copy.deepcopy(input_payload)
    payload["modes"] = {"path": str(modes_path)}
    parsed = FCEnvelopeInput.from_obj(payload, base_dir=tmp_path / "elsewhere")
    assert len(parsed.modes) == 1


@pytest.mark.parametrize(
    "reference",
    [{}, {"path": ""}, {"path": 1}, {"path": "modes.csv", "delimiter": ";"}, {"file": "modes.csv"}],
)
def test_malformed_reference(tmp_path, input_payload, reference):
    _write(tmp_path / "modes.csv", "frequency,coupling\n1200.0,0.5\n")
    payload = copy.deepcopy(input_payload)
    payload["modes"] = reference
    with pytest.raises(InvalidInputError):
        FCEnvelopeInput.from_obj(payload, base_dir=tmp_path)


def test_errors_inside_referenced_csv_are_input_errors(tmp_path, input_payload):
    """CSV の構造の誤りは、読んだ時点で行番号つきで報告される。"""
    _write(tmp_path / "modes.csv", "frequency,coupling\n1200.0,abc\n")
    payload = copy.deepcopy(input_payload)
    payload["modes"] = {"path": "modes.csv"}
    with pytest.raises(InvalidInputError, match="modes.csv:2"):
        FCEnvelopeInput.from_obj(payload, base_dir=tmp_path)


def test_out_of_range_values_in_csv_are_reported_by_mode_index(tmp_path, input_payload):
    """値の範囲は正準化のときに値の型が見るので、位置はモードの番号になる。

    CSV の行番号は構造の誤りにしか付かない。範囲の検査は流儀と単位を消費した
    後でなければできず、その時点では行の出どころが配列かファイルかを区別しない
    （ADR-0051）。
    """
    _write(tmp_path / "modes.csv", "frequency,coupling\n1200.0,0.5\n0.0,0.8\n")
    payload = copy.deepcopy(input_payload)
    payload["modes"] = {"path": "modes.csv"}
    parsed = FCEnvelopeInput.from_obj(payload, base_dir=tmp_path)
    with pytest.raises(InvalidInputError, match=r"modes\[1\]"):
        parsed.to_system()
