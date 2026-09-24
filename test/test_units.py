"""エネルギー単位の換算表（ADR-0054）と、入力の境界でのその消費。

単位を変えても結果が変わらないことが、この一連の作業の主な検証軸になる。同じ物理系を
違う単位で書いた入力が、同一の系と同一のスペクトルを出すことを見る。
"""

from __future__ import annotations

import copy
import json

import numpy as np
import pytest
from conftest import compute_quietly

from fcenvelope import FCEnvelopeInput, units
from fcenvelope.errors import InvalidInputError, UnsupportedUnitError


def _in_unit(value: float, unit: str) -> float:
    """cm^-1 の値を `unit` で書いたときの数値。"""
    return value / units.energy_conversion_factor(unit)


def _envelope(parsed: FCEnvelopeInput):
    return compute_quietly(
        parsed.to_system(),
        temperature=parsed.to_temperature(),
        broadening=parsed.to_broadening(),
        grid=parsed.to_grid(),
    )


def _assert_same_spectrum(left: FCEnvelopeInput, right: FCEnvelopeInput) -> None:
    """2 つの入力が同じスペクトルを出すこと。判定は ADR-0042 の形にする。"""
    expected = _envelope(right).density
    np.testing.assert_allclose(
        _envelope(left).density, expected, rtol=0.0, atol=1e-12 * float(expected.max())
    )


def test_the_canonical_unit_has_a_factor_of_one():
    assert units.CANONICAL_ENERGY_UNIT == "cm^-1"
    assert units.energy_conversion_factor("cm^-1") == 1.0


@pytest.mark.parametrize("unit", sorted(units.ENERGY_UNITS))
def test_round_trip_through_each_unit(unit):
    """cm^-1 -> X -> cm^-1 が元に戻ること。表の各行が逆数として整合している。"""
    factor = units.energy_conversion_factor(unit)
    value = 1234.5
    assert value / factor * factor == pytest.approx(value, rel=1e-14)


@pytest.mark.parametrize(
    ("unit", "expected"),
    [
        # CODATA の既知の値との照合。scipy から導出した係数が桁ごと合っていること。
        ("eV", 8065.543937),
        ("hartree", 219474.6314),
        ("THz", 33.35640952),
        ("kJ/mol", 83.59347229),
        ("kcal/mol", 349.7550879),
    ],
)
def test_known_values(unit, expected):
    assert units.energy_conversion_factor(unit) == pytest.approx(expected, rel=1e-8)


def test_the_conversions_are_consistent_with_each_other():
    """独立に知られている単位どうしの関係が再現されること。"""
    ev = units.energy_conversion_factor("eV")
    hartree = units.energy_conversion_factor("hartree")
    kj = units.energy_conversion_factor("kJ/mol")
    kcal = units.energy_conversion_factor("kcal/mol")

    assert hartree / ev == pytest.approx(27.211386, rel=1e-6)  # 1 hartree [eV]
    assert kcal / kj == pytest.approx(4.184, rel=1e-12)  # 熱化学カロリー


@pytest.mark.parametrize("unit", ["nm", "cm-1", "ev", "", None, 1.0, {"unit": "eV"}])
def test_an_unknown_unit_is_rejected(unit):
    """波長も、綴りや大小の違いも受けない。未知の型でも同じ形で報告する。"""
    with pytest.raises(UnsupportedUnitError, match="unsupported energy unit"):
        units.energy_conversion_factor(unit)


def test_the_error_names_the_known_units():
    with pytest.raises(UnsupportedUnitError, match="kcal/mol"):
        units.energy_conversion_factor("nm")


def test_the_default_frequency_unit_is_the_canonical_one(input_payload):
    """単位フィールドを省いた既存の入力が、そのまま cm^-1 として読まれること。"""
    payload = copy.deepcopy(input_payload)
    del payload["frequency_unit"]
    parsed = FCEnvelopeInput.from_obj(payload)

    assert parsed.frequency_unit == units.CANONICAL_ENERGY_UNIT
    assert parsed.to_system() == FCEnvelopeInput.from_obj(input_payload).to_system()


@pytest.mark.parametrize("unit", sorted(set(units.ENERGY_UNITS) - {"cm^-1"}))
def test_the_same_system_written_in_another_unit(input_payload, unit):
    """cm^-1 で書いた系と、同じ系を別の単位で書いたものが一致すること。"""
    canonical = FCEnvelopeInput.from_obj(input_payload)

    payload = copy.deepcopy(input_payload)
    payload["frequency_unit"] = unit
    for mode in payload["modes"]:
        mode["frequency"] = _in_unit(mode["frequency"], unit)
    converted = FCEnvelopeInput.from_obj(payload)

    for got, want in zip(converted.to_system().modes, canonical.to_system().modes):
        assert got.frequency == pytest.approx(want.frequency, rel=1e-14)
        assert got.huang_rhys == pytest.approx(want.huang_rhys, rel=1e-14)
    _assert_same_spectrum(converted, canonical)


def test_the_frequency_unit_does_not_leak_past_the_boundary(input_payload):
    """正準化の後に単位は残らない。結果は cm^-1 の値だけを持つ（ADR-0054）。"""
    payload = copy.deepcopy(input_payload)
    payload["frequency_unit"] = "eV"
    payload["modes"] = [{"frequency": _in_unit(1200.0, "eV"), "coupling": 0.5}]

    mode = FCEnvelopeInput.from_obj(payload).to_system().modes[0]

    assert mode.frequency == pytest.approx(1200.0, rel=1e-14)


def test_sigma_and_grid_in_another_unit(input_payload):
    """eV で書いた sigma とグリッドが、cm^-1 の等価な入力と同じ結果を出すこと。"""
    canonical = FCEnvelopeInput.from_obj(input_payload)

    payload = copy.deepcopy(input_payload)
    payload["broadening"] = {"sigma": _in_unit(150.0, "eV"), "unit": "eV"}
    payload["grid"] = {
        "e_min": _in_unit(-4500.0, "eV"),
        "e_max": _in_unit(1000.0, "eV"),
        "points": {"de": _in_unit(4.0, "eV")},
        "unit": "eV",
    }
    converted = FCEnvelopeInput.from_obj(payload)

    assert converted.to_broadening().sigma == pytest.approx(150.0, rel=1e-14)
    grid = converted.to_grid()
    assert grid.e_min == pytest.approx(-4500.0, rel=1e-14)
    assert grid.e_max == pytest.approx(1000.0, rel=1e-14)
    assert grid.de == pytest.approx(4.0, rel=1e-14)
    _assert_same_spectrum(converted, canonical)


def test_the_unit_axes_are_independent(input_payload):
    """broadening だけ eV、grid は cm^-1 という混在が通ること（ADR-0053）。"""
    payload = copy.deepcopy(input_payload)
    payload["broadening"] = {"sigma": _in_unit(150.0, "eV"), "unit": "eV"}
    mixed = FCEnvelopeInput.from_obj(payload)

    assert mixed.grid.unit == units.CANONICAL_ENERGY_UNIT
    assert mixed.to_broadening().sigma == pytest.approx(150.0, rel=1e-14)
    _assert_same_spectrum(mixed, FCEnvelopeInput.from_obj(input_payload))


def test_the_block_units_default_to_the_canonical_one(input_payload):
    """単位を書いていない既存の入力が、そのまま cm^-1 として読まれること。"""
    parsed = FCEnvelopeInput.from_obj(input_payload)

    assert parsed.broadening.unit == units.CANONICAL_ENERGY_UNIT
    assert parsed.grid.unit == units.CANONICAL_ENERGY_UNIT
    assert parsed.to_broadening().sigma == 150.0
    assert parsed.to_grid().de == 4.0


@pytest.mark.parametrize("block", ["broadening", "grid"])
def test_an_unknown_block_unit_is_rejected(input_payload, block):
    payload = copy.deepcopy(input_payload)
    payload[block] = {**payload[block], "unit": "nm"}
    with pytest.raises(UnsupportedUnitError):
        FCEnvelopeInput.from_obj(payload)


# --- 値に添えて書く単位（ADR-0072） ------------------------------------------


@pytest.mark.parametrize(
    "written",
    [150.0, [150.0], [150.0, "cm^-1"]],
    ids=["bare", "pair-without-unit", "pair-with-unit"],
)
def test_the_three_ways_of_writing_a_value_agree(input_payload, written):
    """素の数値・`[値]`・`[値, "単位"]` が同じ量を表すこと（ADR-0072）。"""
    payload = copy.deepcopy(input_payload)
    payload["broadening"] = {"sigma": written}

    assert FCEnvelopeInput.from_obj(payload).to_broadening().sigma == 150.0


def test_a_value_may_carry_its_own_unit(input_payload):
    """ブロックの `unit` を書かずに、値の側だけで単位を指定できること。"""
    payload = copy.deepcopy(input_payload)
    payload["broadening"] = {"sigma": [_in_unit(150.0, "eV"), "eV"]}
    converted = FCEnvelopeInput.from_obj(payload)

    assert converted.broadening.unit == units.CANONICAL_ENERGY_UNIT
    assert converted.to_broadening().sigma == pytest.approx(150.0, rel=1e-14)
    _assert_same_spectrum(converted, FCEnvelopeInput.from_obj(input_payload))


def test_the_unit_on_a_value_wins_over_the_block_unit(input_payload):
    """値に添えた単位は、ブロックの単位より優先されること（ADR-0072）。"""
    payload = copy.deepcopy(input_payload)
    payload["broadening"] = {"sigma": [_in_unit(150.0, "eV"), "eV"], "unit": "hartree"}

    parsed = FCEnvelopeInput.from_obj(payload)

    assert parsed.to_broadening().sigma == pytest.approx(150.0, rel=1e-14)


def test_the_block_unit_still_covers_the_values_written_bare(input_payload):
    """1 つのブロックの中で、組と素の数値が混ざってもそれぞれの単位で読まれること。"""
    payload = copy.deepcopy(input_payload)
    payload["grid"] = {
        "e_min": [_in_unit(-4500.0, "eV"), "eV"],  # 自分の単位
        "e_max": 1000.0,  # ブロックの単位
        "points": {"de": 4.0},
        "unit": "cm^-1",
    }
    grid = FCEnvelopeInput.from_obj(payload).to_grid()

    assert grid.e_min == pytest.approx(-4500.0, rel=1e-14)
    assert grid.e_max == pytest.approx(1000.0, rel=1e-14)
    assert grid.de == pytest.approx(4.0, rel=1e-14)


def test_a_mode_may_carry_its_own_frequency_unit(input_payload):
    """モードごとに単位を書けること。書かないモードはトップレベルの既定で読む。"""
    payload = copy.deepcopy(input_payload)
    payload["modes"] = [
        {"frequency": [_in_unit(1200.0, "eV"), "eV"], "coupling": 0.5},
        {"frequency": 450.0, "coupling": 0.8},
    ]
    modes = FCEnvelopeInput.from_obj(payload).to_system().modes

    assert modes[0].frequency == pytest.approx(1200.0, rel=1e-14)
    assert modes[1].frequency == pytest.approx(450.0, rel=1e-14)
    _assert_same_spectrum(
        FCEnvelopeInput.from_obj(payload), FCEnvelopeInput.from_obj(input_payload)
    )


def test_a_coupling_unit_on_the_mode_satisfies_a_dimensioned_convention(input_payload):
    """有次元の流儀で、単位をトップレベルではなく値に添えても通ること。"""
    payload = copy.deepcopy(input_payload)
    payload["coupling_convention"] = "lambda"
    payload["modes"] = [{"frequency": 1200.0, "coupling": [_in_unit(300.0, "eV"), "eV"]}]

    mode = FCEnvelopeInput.from_obj(payload).to_system().modes[0]

    assert mode.huang_rhys == pytest.approx(0.25, rel=1e-14)  # S = lambda / eps


def test_a_unit_on_a_dimensionless_coupling_names_the_mode(input_payload):
    """無次元の流儀に単位を添えた誤りが、そのモードを名指しで報告されること。"""
    payload = copy.deepcopy(input_payload)
    payload["modes"] = [
        {"frequency": 1200.0, "coupling": 0.5},
        {"frequency": 450.0, "coupling": [0.8, "eV"]},
    ]
    parsed = FCEnvelopeInput.from_obj(payload)

    with pytest.raises(InvalidInputError, match=r"modes\[1\]: .*dimensionless"):
        parsed.to_system()


def test_an_unknown_unit_on_a_value_is_rejected(input_payload):
    payload = copy.deepcopy(input_payload)
    payload["broadening"] = {"sigma": [0.0186, "nm"]}

    with pytest.raises(UnsupportedUnitError, match="unsupported energy unit"):
        FCEnvelopeInput.from_obj(payload)


@pytest.mark.parametrize(
    "written",
    [[], [150.0, 1.0, "eV", 1.0], {"value": 150.0, "unit": "eV"}, "wide", True, [None, "eV"]],
    ids=["empty", "too-long", "table", "not-a-number", "bool", "no-value"],
)
def test_a_malformed_value_names_the_ways_of_writing_one(input_payload, written):
    """受け付けるのは 3 つの書き方だけで、誤りの報告がその 3 つを挙げること。"""
    payload = copy.deepcopy(input_payload)
    payload["broadening"] = {"sigma": written}

    with pytest.raises(InvalidInputError, match=r'\[value, "unit"\]'):
        FCEnvelopeInput.from_obj(payload)


def test_the_effective_settings_keep_the_way_the_value_was_written(input_payload):
    """実効設定は書いたままの姿で、そのまま読み返せること（ADR-0065, 0072）。"""
    payload = copy.deepcopy(input_payload)
    payload["broadening"] = {"sigma": [_in_unit(150.0, "eV"), "eV"]}
    parsed = FCEnvelopeInput.from_obj(payload)

    written = json.loads(parsed.to_json())

    assert written["broadening"]["sigma"] == [_in_unit(150.0, "eV"), "eV"]
    assert written["grid"]["e_min"] == -4500.0  # 素で書いたものは素のまま
    assert FCEnvelopeInput.from_json(parsed.to_json()).to_broadening().sigma == (
        pytest.approx(150.0, rel=1e-14)
    )


# --- 正式名・別名・倍率（ADR-0076, 0078） -------------------------------------


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("hartree", (None, "hartree")),
        ([1e-4, "hartree"], (1e-4, "hartree")),
        ((1e-4, "hartree"), (1e-4, "hartree")),
        ([1000, "eV"], (1000.0, "eV")),
    ],
)
def test_the_scale_and_the_name_are_split(written, expected):
    assert units.split_unit(written) == expected


@pytest.mark.parametrize(
    "written",
    [
        [0.0, "eV"],
        [-1.0, "eV"],
        [float("nan"), "eV"],
        [float("inf"), "eV"],
        ["1e-4", "eV"],
        [True, "eV"],
        [1e-4, 1.0],
        [1e-4],
        [1e-4, "eV", 1.0],
        None,
        1.0,
        {"scale": 1e-4, "name": "eV"},
    ],
)
def test_a_malformed_unit_is_rejected(written):
    with pytest.raises(UnsupportedUnitError, match=r'\[<scale>, "<name>"\]'):
        units.split_unit(written)
    with pytest.raises(UnsupportedUnitError, match="unsupported energy unit"):
        units.ENERGY_UNIT_KIND.resolve(written)


@pytest.mark.parametrize("written", ["10^-4 hartree", "1e-4 hartree", "1e-4a.u."])
def test_a_scale_inside_the_name_is_not_parsed(written):
    """倍率を文字列の中に書いても切り出さない。全体が 1 つの未知の名前になる（ADR-0078）。"""
    assert units.split_unit(written) == (None, written)
    with pytest.raises(UnsupportedUnitError, match=r'\[<scale>, "<name>"\]'):
        units.ENERGY_UNIT_KIND.resolve(written)


def test_a_scale_multiplies_the_factor():
    ev = units.energy_conversion_factor("eV")
    assert units.energy_conversion_factor([1e-3, "eV"]) == pytest.approx(1e-3 * ev, rel=1e-15)
    assert units.energy_conversion_factor([2.5, "eV"]) == pytest.approx(2.5 * ev, rel=1e-15)


def test_a_u_is_hartree_in_an_energy_field():
    resolved = units.ENERGY_UNIT_KIND.resolve([1e-4, "a.u."])

    assert resolved.form == (1e-4, "hartree")
    assert units.energy_conversion_factor("a.u.") == units.energy_conversion_factor("hartree")


def test_the_vcc_unit_is_the_hartree_factor_to_the_three_halves():
    """1 E_h/(a_0 sqrt(m_e)) = E_h^{3/2} h_bar^{-1/2}（ADR-0077）。"""
    resolved = units.VCC_UNIT_KIND.resolve("a.u.")

    assert resolved.form == units.VCC_UNIT == "hartree/(bohr*sqrt(m_e))"
    assert resolved.factor == pytest.approx(
        units.energy_conversion_factor("hartree") ** 1.5, rel=1e-15
    )


def _every_way_of_writing(kind: units.UnitKind) -> list[object]:
    names = [*kind.factors, *kind.aliases]
    return [name for name in names] + [
        [scale, name] for name in names for scale in (1e-4, 1e-3, 2.5, 1000)
    ]


@pytest.mark.parametrize(
    "kind", [units.ENERGY_UNIT_KIND, units.VCC_UNIT_KIND], ids=["energy", "vcc"]
)
def test_the_formal_form_reads_back_as_itself(kind):
    """正式形を読み直すと同じ正式形・同じ係数になる（冪等、ADR-0076）。"""
    for written in _every_way_of_writing(kind):
        once = kind.resolve(written)
        twice = kind.resolve(once.form)
        assert twice == once, written
        name = once.form if isinstance(once.form, str) else once.form[1]
        assert name in kind.factors, written


def test_sigma_in_a_u_is_sigma_in_hartree(input_payload):
    in_hartree = _in_unit(150.0, "hartree")
    au, hartree = copy.deepcopy(input_payload), copy.deepcopy(input_payload)
    au["broadening"] = {"sigma": [in_hartree, "a.u."]}
    hartree["broadening"] = {"sigma": [in_hartree, "hartree"]}

    from_au = FCEnvelopeInput.from_obj(au)

    assert from_au.broadening == FCEnvelopeInput.from_obj(hartree).broadening
    assert from_au.to_broadening() == FCEnvelopeInput.from_obj(hartree).to_broadening()


def test_a_value_may_carry_a_scale(input_payload):
    """`[値, 倍率, "単位"]` の 3 要素で、倍率つきの単位を値に添えられること（ADR-0078）。"""
    mev = _in_unit(150.0, "eV") * 1e3
    payload = copy.deepcopy(input_payload)
    payload["broadening"] = {"sigma": [mev, 1e-3, "eV"]}

    parsed = FCEnvelopeInput.from_obj(payload)

    assert parsed.broadening.sigma.unit == (1e-3, "eV")
    assert parsed.to_broadening().sigma == pytest.approx(150.0, rel=1e-13)


def test_a_block_unit_may_carry_a_scale(input_payload):
    """`grid.unit = [0.001, "eV"]` の窓が meV で読まれること。"""
    mev = _in_unit(1.0, "eV") * 1e3  # 1 cm^-1 を meV で書いた数
    payload = copy.deepcopy(input_payload)
    payload["grid"] = {
        "e_min": -4500.0 * mev,
        "e_max": 1000.0 * mev,
        "points": {"de": 4.0 * mev},
        "unit": [1e-3, "eV"],
    }
    grid = FCEnvelopeInput.from_obj(payload).to_grid()

    assert grid.e_min == pytest.approx(-4500.0, rel=1e-13)
    assert grid.e_max == pytest.approx(1000.0, rel=1e-13)
    assert grid.de == pytest.approx(4.0, rel=1e-13)


def test_a_misplaced_unit_element_is_rejected(input_payload):
    """3 要素の値は [値, 倍率, "単位"] の順だけを受ける。"""
    payload = copy.deepcopy(input_payload)
    payload["broadening"] = {"sigma": [150.0, "eV", 1e-3]}

    with pytest.raises(UnsupportedUnitError, match="scale"):
        FCEnvelopeInput.from_obj(payload)


def test_the_effective_settings_write_the_formal_form(input_payload):
    """別名で書いた入力の実効設定に別名は残らず、読み直すと同じ系・条件になる。"""
    payload = copy.deepcopy(input_payload)
    payload["frequency_unit"] = "a.u."
    payload["modes"] = [
        {"frequency": _in_unit(1200.0, "hartree"), "coupling": 0.5},
        {"frequency": [_in_unit(450.0, "hartree") * 1e3, 1e-3, "a.u."], "coupling": 0.8},
    ]
    payload["broadening"] = {"sigma": 150.0, "unit": [1, "cm^-1"]}
    parsed = FCEnvelopeInput.from_obj(payload)

    text = parsed.to_json()
    written = json.loads(text)

    assert "a.u." not in text
    assert written["frequency_unit"] == "hartree"
    assert written["modes"][1]["frequency"][1:] == [1e-3, "hartree"]
    assert written["broadening"]["unit"] == [1.0, "cm^-1"]
    reread = FCEnvelopeInput.from_json(text)
    assert reread == parsed
    assert reread.to_system() == parsed.to_system()
    assert reread.to_broadening() == parsed.to_broadening()


def test_a_toml_input_may_write_the_scale_as_a_number(tmp_path):
    """TOML の数の書き方（`1e-4` / `0.0001`）が、そのまま倍率として読まれること。"""
    path = tmp_path / "input.toml"
    path.write_text(
        """
schema_version = 3
coupling_convention = "lambda"
coupling_unit = [1e-3, "eV"]
temperature = 0.0

[[modes]]
frequency = 1200.0
coupling = 1.0

[[modes]]
frequency = 450.0
coupling = [100.0, 0.0001, "eV"]
""",
        encoding="utf-8",
    )
    parsed = FCEnvelopeInput.from_path(path)
    modes = parsed.to_system().modes
    ev = units.energy_conversion_factor("eV")

    assert parsed.coupling_unit == (1e-3, "eV")
    assert modes[0].huang_rhys == pytest.approx(1e-3 * ev / 1200.0, rel=1e-14)
    assert modes[1].huang_rhys == pytest.approx(1e-2 * ev / 450.0, rel=1e-14)
