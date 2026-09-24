"""モード表 CSV の読み込み（合意文書 modes-csv-20260915、ADR-0019, 0020, 0079）。"""

from __future__ import annotations

import copy
import json

import pytest

from fcenvelope import (
    FCEnvelopeInput,
    InvalidInputError,
    ModeSpec,
    UnsupportedUnitError,
    VibrationalMode,
)
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
        ("frequency,coupling\n", "no data rows"),
        ("", "table file is empty"),
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
    payload["modes"] = {"coupling_convention": "g", "csv": {"path": "modes.csv"}}
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
    payload["modes"] = {"coupling_convention": "g", "csv": {"path": "modes.csv"}}
    parsed = FCEnvelopeInput.from_obj(payload, base_dir=tmp_path)
    assert parsed.modes.rows == [ModeSpec(frequency=1200.0, coupling=0.5)]


def test_absolute_path_ignores_base_dir(tmp_path, input_payload):
    modes_path = _write(tmp_path / "modes.csv", "frequency,coupling\n1200.0,0.5\n")
    payload = copy.deepcopy(input_payload)
    payload["modes"] = {"csv": {"path": str(modes_path)}}
    parsed = FCEnvelopeInput.from_obj(payload, base_dir=tmp_path / "elsewhere")
    assert len(parsed.modes.rows) == 1


@pytest.mark.parametrize(
    "reference",
    [
        {},
        {"path": ""},
        {"path": 1},
        {"path": "modes.csv", "delimiter": ";"},
        {"file": "modes.csv"},
        "modes.csv",
    ],
)
def test_malformed_reference(tmp_path, input_payload, reference):
    _write(tmp_path / "modes.csv", "frequency,coupling\n1200.0,0.5\n")
    payload = copy.deepcopy(input_payload)
    payload["modes"] = {"csv": reference}
    with pytest.raises(InvalidInputError):
        FCEnvelopeInput.from_obj(payload, base_dir=tmp_path)


def test_errors_inside_referenced_csv_are_input_errors(tmp_path, input_payload):
    """CSV の構造の誤りは、読んだ時点で行番号つきで報告される。"""
    _write(tmp_path / "modes.csv", "frequency,coupling\n1200.0,abc\n")
    payload = copy.deepcopy(input_payload)
    payload["modes"] = {"coupling_convention": "g", "csv": {"path": "modes.csv"}}
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
    payload["modes"] = {"coupling_convention": "g", "csv": {"path": "modes.csv"}}
    parsed = FCEnvelopeInput.from_obj(payload, base_dir=tmp_path)
    with pytest.raises(InvalidInputError, match=r"modes\.rows\[1\]"):
        parsed.to_system()


# --- 列の並びと単位（ADR-0079） ------------------------------------------------


def _csv_payload(input_payload, **modes: object) -> dict:
    payload = copy.deepcopy(input_payload)
    payload["modes"] = modes
    return payload


def test_columns_set_the_order_of_a_headerless_file(tmp_path, input_payload):
    _write(tmp_path / "modes.csv", "0.5,1200.0\n0.8,450.0\n")
    payload = _csv_payload(
        input_payload, csv={"path": "modes.csv", "columns": ["coupling", "frequency"]}
    )
    parsed = FCEnvelopeInput.from_obj(payload, base_dir=tmp_path)
    assert parsed == FCEnvelopeInput.from_obj(input_payload)


def test_default_columns_may_be_written_out(tmp_path, input_payload):
    """`columns` を省くのと、既定の並びを名前だけで書くのは同じ。"""
    _write(tmp_path / "modes.csv", "1200.0,0.5\n450.0,0.8\n")
    written = FCEnvelopeInput.from_obj(
        _csv_payload(
            input_payload, csv={"path": "modes.csv", "columns": ["frequency", "coupling"]}
        ),
        base_dir=tmp_path,
    )
    omitted = FCEnvelopeInput.from_obj(
        _csv_payload(input_payload, csv={"path": "modes.csv"}), base_dir=tmp_path
    )
    assert written == omitted


def test_a_unit_on_a_column_applies_to_every_value_in_it(tmp_path, input_payload):
    """列に添えた単位は、その列の値に `[値, "単位"]` と添えたのと同じ。"""
    _write(tmp_path / "modes.csv", "0.15,0.5\n")
    from_csv = FCEnvelopeInput.from_obj(
        _csv_payload(
            input_payload,
            csv={"path": "modes.csv", "columns": [["frequency", "eV"], "coupling"]},
        ),
        base_dir=tmp_path,
    )
    inline = FCEnvelopeInput.from_obj(
        _csv_payload(input_payload, rows=[{"frequency": [0.15, "eV"], "coupling": 0.5}])
    )
    assert from_csv == inline
    assert from_csv.to_system() == inline.to_system()


def test_a_column_unit_wins_over_the_table_default(tmp_path, input_payload):
    _write(tmp_path / "modes.csv", "150.0,0.5\n")
    parsed = FCEnvelopeInput.from_obj(
        _csv_payload(
            input_payload,
            frequency_unit="eV",
            csv={"path": "modes.csv", "columns": [["frequency", 1e-3, "eV"], "coupling"]},
        ),
        base_dir=tmp_path,
    )
    in_ev = FCEnvelopeInput.from_obj(
        _csv_payload(input_payload, frequency_unit="eV", rows=[{"frequency": 0.15, "coupling": 0.5}])
    )
    assert parsed.to_system().modes[0].frequency == pytest.approx(
        in_ev.to_system().modes[0].frequency, rel=1e-14
    )


def test_a_column_without_a_unit_takes_the_table_default(tmp_path, input_payload):
    _write(tmp_path / "modes.csv", "0.15,0.5\n")
    from_csv = FCEnvelopeInput.from_obj(
        _csv_payload(input_payload, frequency_unit="eV", csv={"path": "modes.csv"}),
        base_dir=tmp_path,
    )
    inline = FCEnvelopeInput.from_obj(
        _csv_payload(input_payload, frequency_unit="eV", rows=[{"frequency": 0.15, "coupling": 0.5}])
    )
    assert from_csv == inline


def test_an_alias_on_a_coupling_column_takes_the_convention_kind(tmp_path, input_payload):
    """`a.u.` は流儀 vcc の列では V の正式名になる（ADR-0076, 0077）。"""
    _write(tmp_path / "modes.csv", "500.0,-0.3\n")
    from_csv = FCEnvelopeInput.from_obj(
        _csv_payload(
            input_payload,
            coupling_convention="vcc",
            csv={"path": "modes.csv", "columns": ["frequency", ["coupling", 1e-4, "a.u."]]},
        ),
        base_dir=tmp_path,
    )
    inline = FCEnvelopeInput.from_obj(
        _csv_payload(
            input_payload,
            coupling_convention="vcc",
            rows=[{"frequency": 500.0, "coupling": [-0.3, 1e-4, "a.u."]}],
        )
    )
    assert from_csv == inline
    assert from_csv.modes.rows[0].coupling.unit == (1e-4, "hartree/(bohr*sqrt(m_e))")


def test_a_unit_on_a_dimensionless_coupling_column_is_refused(tmp_path, input_payload):
    _write(tmp_path / "modes.csv", "1200.0,0.5\n")
    parsed = FCEnvelopeInput.from_obj(
        _csv_payload(
            input_payload,
            coupling_convention="g",
            csv={"path": "modes.csv", "columns": ["frequency", ["coupling", "eV"]]},
        ),
        base_dir=tmp_path,
    )
    with pytest.raises(InvalidInputError, match=r"modes\.rows\[0\]: .*dimensionless"):
        parsed.to_system()


def test_the_effective_settings_carry_the_column_units(tmp_path, input_payload):
    """列の単位は各値に添えた形で書き出され、そのまま読み返せる（ADR-0065, 0079）。"""
    _write(tmp_path / "modes.csv", "0.15,0.5\n")
    parsed = FCEnvelopeInput.from_obj(
        _csv_payload(
            input_payload,
            csv={"path": "modes.csv", "columns": [["frequency", "eV"], "coupling"]},
        ),
        base_dir=tmp_path,
    )
    written = json.loads(parsed.to_json())
    assert written["modes"]["rows"] == [{"frequency": [0.15, "eV"], "coupling": 0.5}]
    assert "csv" not in written["modes"]
    assert FCEnvelopeInput.from_json(parsed.to_json()) == parsed


def test_a_header_in_the_order_of_the_columns_is_read(tmp_path, input_payload):
    _write(tmp_path / "modes.csv", "coupling,frequency\n0.5,1200.0\n0.8,450.0\n")
    parsed = FCEnvelopeInput.from_obj(
        _csv_payload(
            input_payload, csv={"path": "modes.csv", "columns": ["coupling", "frequency"]}
        ),
        base_dir=tmp_path,
    )
    assert parsed == FCEnvelopeInput.from_obj(input_payload)


def test_a_header_that_disagrees_with_the_columns_is_refused(tmp_path, input_payload):
    """どちらの並びを信じるべきかは決められないので止める（ADR-0079）。"""
    _write(tmp_path / "modes.csv", "frequency,coupling\n1200.0,0.5\n")
    payload = _csv_payload(
        input_payload, csv={"path": "modes.csv", "columns": ["coupling", "frequency"]}
    )
    with pytest.raises(InvalidInputError, match=r"modes\.csv:1: the header .* does not match"):
        FCEnvelopeInput.from_obj(payload, base_dir=tmp_path)


@pytest.mark.parametrize(
    "columns",
    [
        ["frequency"],
        ["frequency", "coupling", "label"],
        ["frequency", "frequency"],
        ["frequency", "Coupling"],
        ["frequency", []],
        ["frequency", ["coupling", "eV", "extra", "more"]],
        ["frequency", 1],
        "frequency,coupling",
    ],
)
def test_malformed_columns(tmp_path, input_payload, columns):
    _write(tmp_path / "modes.csv", "1200.0,0.5\n")
    payload = _csv_payload(input_payload, csv={"path": "modes.csv", "columns": columns})
    with pytest.raises(InvalidInputError, match=r"modes\.csv\.columns"):
        FCEnvelopeInput.from_obj(payload, base_dir=tmp_path)


def test_an_unknown_unit_on_a_column_names_the_column(tmp_path, input_payload):
    _write(tmp_path / "modes.csv", "1200.0,0.5\n")
    payload = _csv_payload(
        input_payload, csv={"path": "modes.csv", "columns": [["frequency", "nm"], "coupling"]}
    )
    with pytest.raises(UnsupportedUnitError, match=r"modes\.csv\.columns: frequency: "):
        FCEnvelopeInput.from_obj(payload, base_dir=tmp_path)


def test_rows_and_csv_are_exclusive(tmp_path, input_payload):
    _write(tmp_path / "modes.csv", "1200.0,0.5\n")
    payload = copy.deepcopy(input_payload)
    payload["modes"]["csv"] = {"path": "modes.csv"}
    with pytest.raises(InvalidInputError, match="not both"):
        FCEnvelopeInput.from_obj(payload, base_dir=tmp_path)


def test_either_rows_or_csv_is_required(input_payload):
    payload = _csv_payload(input_payload, coupling_convention="g")
    with pytest.raises(InvalidInputError, match=r"\[\[modes\.rows\]\]"):
        FCEnvelopeInput.from_obj(payload)


def test_a_list_of_modes_points_to_the_rows(input_payload):
    """版 3 までの `[[modes]]` の並びは、版 4 の書き方を添えて断る。"""
    payload = copy.deepcopy(input_payload)
    payload["modes"] = [{"frequency": 1200.0, "coupling": 0.5}]
    with pytest.raises(InvalidInputError, match=r"\[\[modes\.rows\]\]"):
        FCEnvelopeInput.from_obj(payload)


def test_units_are_no_longer_written_at_the_top_level(input_payload):
    """単位と流儀はモード表のブロックに置く（ADR-0079）。"""
    payload = copy.deepcopy(input_payload)
    payload["frequency_unit"] = "cm^-1"
    with pytest.raises(InvalidInputError, match="frequency_unit"):
        FCEnvelopeInput.from_obj(payload)
