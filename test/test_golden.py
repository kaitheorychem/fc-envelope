"""ゴールデンケース: 外部の類似プログラムの出力との突き合わせ（ADR-0082）。

`test/golden/` の下のディレクトリ 1 つが 1 ケースで、中身は次のとおり。

- `case.toml`   — 参照データの出どころ、比べる表現、許容差
- `input.toml`  — 本プログラムの入力ファイル（参照データと同じ条件）
- 参照データの CSV — `case.toml` に書いたパスと列で読む

ディレクトリを数え上げるので、ケースを足せばそのケースも自動的に検証される。形式の
説明と手順は `docs/dev/golden-tests.md` にある。
"""

from __future__ import annotations

import tomllib
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from fcenvelope import FCEnvelopeInput, compute_envelope, compute_fc_lines
from fcenvelope.errors import InvalidInputError, NumericalQualityWarning
from fcenvelope.inputs import CsvColumn, Dimensioned, csv_columns, read_csv_table
from fcenvelope.units import CANONICAL_ENERGY_UNIT, ENERGY_UNIT_KIND

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

#: ケースの記述と本プログラムの入力ファイルの名前。どのケースでも同じ名前にする。
CASE_FILE = "case.toml"
INPUT_FILE = "input.toml"

CASES = sorted(path.parent for path in GOLDEN_DIR.glob(f"*/{CASE_FILE}"))


# ---------------------------------------------------------------------------
# case.toml の形


class _Block(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Source(_Block):
    """参照データの出どころ。比較には使わず、後から読む人のために残す。"""

    program: str = Field(min_length=1)
    version: str = ""
    note: str = ""


class CsvReference(_Block):
    """参照データの CSV。書き方は入力ファイルの `modes.csv` と同じ（ADR-0079）。"""

    path: str = Field(min_length=1)
    columns: list[object] | None = None


class EnvelopeReference(_Block):
    """エンベロープの参照データ。列は `energy` と `density`。"""

    csv: CsvReference
    tolerance: float = Field(gt=0)
    """面積 1 に正規化した後の、差の最大値を参照の最大値で割ったものの上限。"""


class LinesReference(_Block):
    """線の参照データ。列は `energy` と `weight`。"""

    csv: CsvReference
    energy_tolerance: Dimensioned
    """同じ線とみなすエネルギーの差。素の数値なら cm^-1。"""
    tolerance: float = Field(gt=0)
    """重みの差（絶対値）の上限。"""


class GoldenCase(_Block):
    source: Source
    envelope: EnvelopeReference | None = None
    lines: LinesReference | None = None

    @model_validator(mode="after")
    def _compares_something(self) -> "GoldenCase":
        if self.envelope is None and self.lines is None:
            raise ValueError("write [envelope], [lines] or both")
        return self


def load_case(directory: Path) -> GoldenCase:
    path = directory / CASE_FILE
    try:
        return GoldenCase.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))
    except (ValidationError, tomllib.TOMLDecodeError) as exc:
        raise InvalidInputError(f"{path}: {exc}") from exc


# ---------------------------------------------------------------------------
# 参照データの CSV


def _energy_unit(written: object):
    return ENERGY_UNIT_KIND.resolve(written).form


def _dimensionless(written: object):
    raise InvalidInputError(
        f"this column is compared without a unit, got {written!r} "
        "(the envelope is normalized before comparison; line weights are dimensionless)"
    )


class _ReferenceRow(_Block):
    """参照データの 1 行。値の列は `density` か `weight` のどちらか 1 つ。"""

    energy: Dimensioned
    density: float | None = None
    weight: float | None = None


@dataclass(frozen=True)
class ReferenceTable:
    """参照データ。エネルギーは cm^-1 で、昇順に並べ替えてある。"""

    energy: np.ndarray
    value: np.ndarray


def read_reference(directory: Path, reference: CsvReference, value: str) -> ReferenceTable:
    """参照データの CSV を読む。列は `energy` と `value` の 2 つ。"""
    units = {"energy": _energy_unit, value: _dimensionless}
    explicit = reference.columns is not None
    columns = (
        csv_columns(reference.columns, units, location=f"{value} csv.columns")
        if explicit
        else [CsvColumn(name) for name in units]
    )
    rows = read_csv_table(
        directory / reference.path, columns, _ReferenceRow.model_validate, explicit=explicit
    )
    energy = np.array([row.energy.in_canonical(CANONICAL_ENERGY_UNIT) for row in rows])
    values = np.array([getattr(row, value) for row in rows])
    order = np.argsort(energy, kind="stable")
    energy, values = energy[order], values[order]
    if value == "density" and np.any(np.diff(energy) <= 0):
        raise InvalidInputError(f"{reference.path}: energies must not repeat")
    return ReferenceTable(energy, values)


# ---------------------------------------------------------------------------
# 比較


def _area(energy: np.ndarray, density: np.ndarray) -> float:
    return float(np.sum(np.diff(energy) * (density[1:] + density[:-1]) / 2.0))


def envelope_deviation(
    reference: ReferenceTable, energy: np.ndarray, density: np.ndarray
) -> tuple[float, float]:
    """エンベロープのずれ。(ずれ, 最もずれたエネルギー [cm^-1]) を返す。

    計算結果を参照の点へ線形補間し、両方を参照の点の上で面積 1 に正規化してから
    比べる。ずれは差の絶対値の最大を参照の最大値で割ったもの。
    """
    if reference.energy.size < 2:
        raise InvalidInputError("the envelope reference needs at least 2 points")
    if reference.energy[0] < energy[0] or reference.energy[-1] > energy[-1]:
        raise InvalidInputError(
            f"the reference spans [{reference.energy[0]}, {reference.energy[-1]}] cm^-1, "
            f"beyond the computed window [{energy[0]}, {energy[-1]}] cm^-1 "
            "(widen grid.e_min / grid.e_max in input.toml)"
        )
    computed = np.interp(reference.energy, energy, density)
    ref = reference.value / _area(reference.energy, reference.value)
    computed = computed / _area(reference.energy, computed)
    difference = np.abs(computed - ref)
    worst = int(np.argmax(difference))
    return float(difference[worst] / np.max(ref)), float(reference.energy[worst])


@dataclass(frozen=True)
class LineGroup:
    """同じ線とみなした参照と計算の線の組。重みはそれぞれの和。"""

    energy: float
    reference: float
    computed: float

    @property
    def deviation(self) -> float:
        return abs(self.computed - self.reference)


def group_lines(
    reference: ReferenceTable,
    energy: np.ndarray,
    weight: np.ndarray,
    energy_tolerance: float,
) -> list[LineGroup]:
    """参照と計算の線を、エネルギーの差が `energy_tolerance` 以下のもの同士でまとめる。

    縮退した線（数え方がプログラムごとに違う）は 1 つにまとまり、重みは和で比べる。
    片方にしかない線は、もう片方の重みを 0 として残る。
    """
    energies = np.concatenate([reference.energy, energy])
    weights = np.concatenate([reference.value, weight])
    is_reference = np.concatenate(
        [np.ones(reference.energy.size, bool), np.zeros(energy.size, bool)]
    )
    order = np.argsort(energies, kind="stable")
    groups: list[LineGroup] = []
    members: list[int] = []

    def close() -> None:
        at = energies[members]
        ref = sum(weights[i] for i in members if is_reference[i])
        computed = sum(weights[i] for i in members if not is_reference[i])
        groups.append(LineGroup(float(at.mean()), float(ref), float(computed)))

    for i in order:
        if members and energies[i] - energies[members[-1]] > energy_tolerance:
            close()
            members = []
        members.append(int(i))
    if members:
        close()
    return groups


def _compute_strictly(function, *args, **kwargs):
    """品質警告を誤りとして計算する。警告の出る条件はゴールデンケースにしない。"""
    with warnings.catch_warnings():
        warnings.simplefilter("error", NumericalQualityWarning)
        return function(*args, **kwargs)


# ---------------------------------------------------------------------------
# ケースそのもの


def test_there_is_at_least_one_case():
    assert CASES


def _cases_with(block: str) -> list[Path]:
    return [case for case in CASES if getattr(load_case(case), block) is not None]


@pytest.mark.parametrize("directory", _cases_with("envelope"), ids=lambda p: p.name)
def test_envelope_matches_the_reference(directory):
    case = load_case(directory)
    parsed = FCEnvelopeInput.from_path(directory / INPUT_FILE)
    result = _compute_strictly(
        compute_envelope,
        parsed.to_system(),
        temperature=parsed.to_temperature(),
        broadening=parsed.to_broadening(),
        grid=parsed.to_grid(),
    )
    reference = read_reference(directory, case.envelope.csv, "density")

    deviation, at = envelope_deviation(reference, result.energy, result.density)

    assert deviation <= case.envelope.tolerance, (
        f"{case.source.program}: deviation {deviation:.3e} at E = {at} cm^-1 "
        f"exceeds tolerance {case.envelope.tolerance:.3e}"
    )


@pytest.mark.parametrize("directory", _cases_with("lines"), ids=lambda p: p.name)
def test_lines_match_the_reference(directory):
    case = load_case(directory)
    parsed = FCEnvelopeInput.from_path(directory / INPUT_FILE)
    result = _compute_strictly(
        compute_fc_lines,
        parsed.to_system(),
        temperature=parsed.to_temperature(),
        selection=parsed.to_selection(),
    )
    reference = read_reference(directory, case.lines.csv, "weight")
    energy_tolerance = case.lines.energy_tolerance.in_canonical(CANONICAL_ENERGY_UNIT)

    groups = group_lines(reference, result.energies, result.weights, energy_tolerance)
    failing = sorted(
        (group for group in groups if group.deviation > case.lines.tolerance),
        key=lambda group: -group.deviation,
    )

    assert not failing, f"{case.source.program}: {len(failing)} line(s) differ, worst " + ", ".join(
        f"E = {g.energy:.4f} cm^-1 (reference {g.reference:.6e}, computed {g.computed:.6e})"
        for g in failing[:5]
    )


# ---------------------------------------------------------------------------
# 形式の決まり


def _write_case(directory: Path, case: str, **files: str) -> Path:
    directory.mkdir(exist_ok=True)
    (directory / CASE_FILE).write_text(case, encoding="utf-8")
    for name, text in files.items():
        (directory / name.replace("_", ".")).write_text(text, encoding="utf-8")
    return directory


_ENVELOPE_CASE = """
[source]
program = "test"

[envelope]
csv = {{ path = "envelope.csv"{columns} }}
tolerance = 1e-3
"""


def test_a_case_must_compare_something(tmp_path):
    _write_case(tmp_path, '[source]\nprogram = "test"\n')
    with pytest.raises(InvalidInputError, match="write \\[envelope\\], \\[lines\\] or both"):
        load_case(tmp_path)


def test_a_case_rejects_unknown_keys(tmp_path):
    _write_case(tmp_path, _ENVELOPE_CASE.format(columns="") + "normalize = false\n")
    with pytest.raises(InvalidInputError, match="normalize"):
        load_case(tmp_path)


def test_reference_columns_take_units_the_way_input_csv_does(tmp_path):
    case = _write_case(
        tmp_path,
        _ENVELOPE_CASE.format(columns=', columns = ["density", ["energy", "eV"]]'),
        envelope_csv="2.0,0.1\n1.0,0.2\n",
    )
    reference = read_reference(case, load_case(case).envelope.csv, "density")

    np.testing.assert_allclose(reference.energy, [0.1 * 8065.54, 0.2 * 8065.54], rtol=1e-5)
    np.testing.assert_array_equal(reference.value, [2.0, 1.0])


def test_reference_without_columns_reads_the_header_or_energy_first(tmp_path):
    case = _write_case(
        tmp_path, _ENVELOPE_CASE.format(columns=""), envelope_csv="density,energy\n3.0,-5.0\n"
    )
    reference = read_reference(case, load_case(case).envelope.csv, "density")

    np.testing.assert_array_equal(reference.energy, [-5.0])
    np.testing.assert_array_equal(reference.value, [3.0])


def test_the_value_column_takes_no_unit(tmp_path):
    case = _write_case(
        tmp_path,
        _ENVELOPE_CASE.format(columns=', columns = ["energy", ["density", "eV"]]'),
        envelope_csv="0.0,1.0\n",
    )
    with pytest.raises(InvalidInputError, match="compared without a unit"):
        read_reference(case, load_case(case).envelope.csv, "density")


def test_envelope_reference_energies_must_not_repeat(tmp_path):
    case = _write_case(
        tmp_path, _ENVELOPE_CASE.format(columns=""), envelope_csv="0.0,1.0\n0.0,2.0\n"
    )
    with pytest.raises(InvalidInputError, match="must not repeat"):
        read_reference(case, load_case(case).envelope.csv, "density")


def test_envelope_comparison_ignores_the_scale_of_the_reference():
    energy = np.linspace(-10.0, 10.0, 201)
    density = np.exp(-(energy**2) / 8.0)
    reference = ReferenceTable(energy[::5], 1234.0 * density[::5])

    deviation, _ = envelope_deviation(reference, energy, density)

    assert deviation < 1e-12


def test_envelope_reference_must_lie_inside_the_computed_window():
    energy = np.linspace(-10.0, 10.0, 21)
    reference = ReferenceTable(np.array([-11.0, 0.0]), np.array([1.0, 1.0]))
    with pytest.raises(InvalidInputError, match="beyond the computed window"):
        envelope_deviation(reference, energy, np.ones_like(energy))


def test_degenerate_lines_are_compared_by_their_sum():
    """参照が 1 本に書いた線を、計算が 2 本に分けていても一致とみなす。"""
    reference = ReferenceTable(np.array([-900.0, 0.0]), np.array([0.3, 0.7]))
    energy = np.array([0.0, -900.0, -900.004])
    weight = np.array([0.7, 0.1, 0.2])

    groups = group_lines(reference, energy, weight, energy_tolerance=0.01)

    assert [(g.reference, g.computed) for g in groups] == [
        pytest.approx((0.3, 0.3)),
        pytest.approx((0.7, 0.7)),
    ]


def test_a_line_on_one_side_only_is_compared_with_zero():
    reference = ReferenceTable(np.array([0.0]), np.array([1.0]))

    groups = group_lines(reference, np.array([0.0, -1200.0]), np.array([1.0, 1e-6]), 0.01)

    assert [(g.energy, g.reference, g.computed) for g in groups] == [
        (-1200.0, 0.0, 1e-6),
        (0.0, 1.0, 1.0),
    ]
