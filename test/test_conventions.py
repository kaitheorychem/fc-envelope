"""振電相互作用の流儀（g / delta / huang_rhys / lambda / vcc）の正準化。"""

from __future__ import annotations

import math

import numpy as np
import pytest
from conftest import compute_quietly

from fcenvelope import (
    CouplingConvention,
    FCEnvelopeInput,
    VibrationalMode,
    VibrationalSystem,
    units,
)
from fcenvelope.errors import InvalidInputError, UnsupportedUnitError


def _payload(convention: str, coupling: float, **extra: object) -> dict:
    return {
        "schema_version": 3,
        "frequency_unit": "cm^-1",
        "coupling_convention": convention,
        **extra,
        "modes": [{"frequency": 1200.0, "coupling": coupling}],
        "temperature": 300.0,
        "broadening": {"sigma": 150.0},
        "grid": {"e_min": -4000.0, "e_max": 1000.0, "points": {"de": 5.0}},
    }


def _envelope(parsed: FCEnvelopeInput):
    return compute_quietly(
        parsed.to_system(),
        temperature=parsed.to_temperature(),
        broadening=parsed.to_broadening(),
        grid=parsed.to_grid(),
    )


def test_registry_conversions():
    assert units.G.to_huang_rhys(0.5, 1200.0) == 0.25
    assert units.DELTA.to_huang_rhys(1.0, 1200.0) == 0.5
    assert units.HUANG_RHYS.to_huang_rhys(0.25, 1200.0) == 0.25


def test_the_dimensionless_conventions_ignore_the_frequency():
    """g / Delta / huang_rhys は omega を要しない（`docs/theory/vcc.md` の表）。"""
    for convention in (units.G, units.DELTA, units.HUANG_RHYS):
        assert convention.is_dimensionless
        assert convention.to_huang_rhys(0.5, 1200.0) == convention.to_huang_rhys(
            0.5, 300.0
        )


def test_a_dimensionless_convention_rejects_a_coupling_unit():
    with pytest.raises(InvalidInputError, match="dimensionless"):
        units.G.check_coupling_unit("cm^-1")
    assert units.G.check_coupling_unit(None) is None


def test_the_convention_type_carries_its_unit_kind():
    """有次元の流儀は単位の種類を持ち、無次元の流儀は持たない（ADR-0076）。"""
    assert units.LAMBDA.unit_kind is units.ENERGY_UNIT_KIND
    assert units.VCC.unit_kind is units.VCC_UNIT_KIND
    for convention in (units.G, units.DELTA, units.HUANG_RHYS):
        assert convention.unit_kind is None
    custom = CouplingConvention(
        name="custom", unit_kind=units.ENERGY_UNIT_KIND, converter=lambda v, _: v
    )
    assert not custom.is_dimensionless


def test_an_unknown_name_names_the_known_conventions():
    with pytest.raises(InvalidInputError, match="huang_rhys"):
        units.coupling_convention("Delta")


def test_g_and_huang_rhys_agree():
    """g = 0.5 と huang_rhys = 0.25 は同一の結果を与える。"""
    from_g = FCEnvelopeInput.from_obj(_payload("g", 0.5))
    from_s = FCEnvelopeInput.from_obj(_payload("huang_rhys", 0.25))

    expected = VibrationalSystem([VibrationalMode(frequency=1200.0, huang_rhys=0.25)])
    assert from_g.to_system() == from_s.to_system() == expected

    result_g = _envelope(from_g)
    result_s = _envelope(from_s)

    np.testing.assert_array_equal(result_g.density, result_s.density)
    assert result_g.system.reorganization_energy == result_s.system.reorganization_energy


def test_delta_and_g_agree():
    """Delta = sqrt(2)*g は同じ S を与える（`docs/theory/vcc.md` の表）。"""
    g = 0.5
    from_g = FCEnvelopeInput.from_obj(_payload("g", g))
    from_delta = FCEnvelopeInput.from_obj(_payload("delta", math.sqrt(2.0) * g))

    assert from_delta.to_system().modes[0].huang_rhys == pytest.approx(
        from_g.to_system().modes[0].huang_rhys
    )
    # sqrt(2) を往復するぶん S が 1 ULP ずれるので、判定は最大値で正規化した
    # 相対誤差にする（ADR-0042）。要素ごとの相対誤差は裾がほぼ 0 なので使えない。
    from_delta_density = _envelope(from_delta).density
    from_g_density = _envelope(from_g).density
    np.testing.assert_allclose(
        from_delta_density,
        from_g_density,
        rtol=0.0,
        atol=1e-12 * float(from_g_density.max()),
    )


def test_delta_is_dimensionless():
    """Delta は無次元なので coupling の単位を添えるのは誤り（ADR-0055）。"""
    assert units.DELTA.is_dimensionless
    assert units.DELTA.check_coupling_unit(None) is None
    with pytest.raises(InvalidInputError, match="dimensionless"):
        units.DELTA.check_coupling_unit("eV")


def test_default_convention_is_g():
    payload = _payload("g", 0.5)
    del payload["coupling_convention"]
    parsed = FCEnvelopeInput.from_obj(payload)
    assert parsed.convention is units.G
    assert parsed.to_system().modes[0].huang_rhys == 0.25


@pytest.mark.parametrize("convention", ["Delta", "reorganization", ""])
def test_unknown_convention_is_rejected(convention):
    with pytest.raises(InvalidInputError):
        FCEnvelopeInput.from_obj(_payload(convention, 0.5))


def test_lambda_and_huang_rhys_agree():
    """S = lambda / eps。lambda を eV で書いても同じ系になる（ADR-0055）。"""
    huang_rhys = 0.25
    frequency = 1200.0
    in_ev = huang_rhys * frequency / units.energy_conversion_factor("eV")

    from_s = FCEnvelopeInput.from_obj(_payload("huang_rhys", huang_rhys))
    from_lambda = FCEnvelopeInput.from_obj(
        _payload("lambda", in_ev, coupling_unit="eV")
    )

    assert from_lambda.to_system().modes[0].huang_rhys == pytest.approx(
        huang_rhys, rel=1e-14
    )
    expected = _envelope(from_s).density
    np.testing.assert_allclose(
        _envelope(from_lambda).density,
        expected,
        rtol=0.0,
        atol=1e-12 * float(expected.max()),
    )


def test_lambda_in_the_canonical_unit_is_the_reorganization_energy():
    """cm^-1 で書いた lambda が、そのまま系の再配列エネルギーになること。"""
    parsed = FCEnvelopeInput.from_obj(
        _payload("lambda", 300.0, coupling_unit="cm^-1")
    )
    assert parsed.to_system().reorganization_energy == pytest.approx(300.0, rel=1e-14)


@pytest.mark.parametrize("convention", ["lambda", "vcc"])
def test_a_dimensioned_convention_needs_a_coupling_unit(convention):
    """有次元の流儀で単位を省くと拒否される（check_coupling_unit の一方の枝）。"""
    with pytest.raises(UnsupportedUnitError, match="carries units"):
        FCEnvelopeInput.from_obj(_payload(convention, 300.0)).to_system()


@pytest.mark.parametrize("convention", ["g", "delta", "huang_rhys"])
def test_a_dimensionless_convention_refuses_a_coupling_unit(convention):
    """無次元の流儀に単位を添えると拒否される（もう一方の枝）。"""
    payload = _payload(convention, 0.5, coupling_unit="eV")
    with pytest.raises(InvalidInputError, match="dimensionless"):
        FCEnvelopeInput.from_obj(payload).to_system()


def test_an_unknown_coupling_unit_is_rejected():
    with pytest.raises(UnsupportedUnitError, match="unsupported energy unit"):
        FCEnvelopeInput.from_obj(_payload("lambda", 300.0, coupling_unit="nm"))


def test_the_coupling_unit_is_omitted_by_default():
    """単位を書いていない既存の入力は、無次元の流儀として読まれ続ける。"""
    parsed = FCEnvelopeInput.from_obj(_payload("g", 0.5))
    assert parsed.coupling_unit is None
    assert parsed.to_system().modes[0].huang_rhys == 0.25


# --- a.u. と倍率を流儀が読み分けること（ADR-0076） ---------------------------


def test_lambda_reads_a_u_as_hartree():
    """流儀 lambda の欄では `a.u.` はエネルギーの `hartree` になる。"""
    parsed = FCEnvelopeInput.from_obj(_payload("lambda", 1e-3, coupling_unit="a.u."))

    assert parsed.coupling_unit == "hartree"
    same = FCEnvelopeInput.from_obj(_payload("lambda", 1e-3, coupling_unit="hartree"))
    assert parsed.to_system() == same.to_system()


def test_the_same_alias_resolves_by_the_convention():
    """同じ `a.u.` でも、流儀 vcc の欄では V の正式名になる。"""
    parsed = FCEnvelopeInput.from_obj(
        _payload("vcc", -0.3, coupling_unit="10^-4 a.u.")
    )
    assert parsed.coupling_unit == "10^-4 hartree/(bohr*sqrt(m_e))"


def test_a_unit_on_the_mode_is_resolved_by_the_convention():
    """モードの値に添えた単位も、流儀が決める種類で正式形になる。"""
    parsed = FCEnvelopeInput.from_obj(_payload("vcc", [-0.3, "10^-4 a.u."]))

    assert parsed.modes[0].coupling.unit == "10^-4 hartree/(bohr*sqrt(m_e))"


def test_the_caller_s_dictionary_is_left_alone():
    """正式形への置き換えは写しに対して行い、渡した辞書は書き換えない。"""
    payload = _payload("vcc", [-0.3, "10^-4 a.u."], coupling_unit="a.u.")
    FCEnvelopeInput.from_obj(payload)

    assert payload["coupling_unit"] == "a.u."
    assert payload["modes"][0]["coupling"] == [-0.3, "10^-4 a.u."]


def test_an_alias_on_a_dimensionless_coupling_is_still_refused():
    """無次元の流儀に `a.u.` を添えても、今までどおり拒否される。"""
    parsed = FCEnvelopeInput.from_obj(_payload("g", 0.5, coupling_unit="a.u."))
    with pytest.raises(InvalidInputError, match="dimensionless"):
        parsed.to_system()


@pytest.mark.parametrize("unit", ["1 2 a.u.", "0 a.u.", "-1 a.u."])
def test_a_malformed_coupling_unit_is_refused_even_without_units(unit):
    """書き方の誤りは流儀によらず読んだ時点で報告される。"""
    with pytest.raises(UnsupportedUnitError, match="scale"):
        FCEnvelopeInput.from_obj(_payload("g", 0.5, coupling_unit=unit))


def test_an_unknown_coupling_unit_names_its_location():
    """流儀が引き当てられない単位は、書かれた位置を添えて報告される。"""
    with pytest.raises(UnsupportedUnitError, match=r"coupling_unit: .*vibronic"):
        FCEnvelopeInput.from_obj(_payload("vcc", -0.3, coupling_unit="eV"))
    with pytest.raises(UnsupportedUnitError, match=r"modes\[0\]\.coupling: "):
        FCEnvelopeInput.from_obj(_payload("vcc", [-0.3, "eV"]))


# --- 流儀 vcc（ADR-0077） -----------------------------------------------------


#: 相手プログラムの出力の 1 モード（ADR-0077 の「確かめたこと」）。
_OUTPUT_FREQUENCY = 500.0
_OUTPUT_VCC = [-0.3, "10^-4 a.u."]


def _vcc_payload(coupling: object, **extra: object) -> dict:
    payload = _payload("vcc", 0.0, **extra)
    payload["modes"] = [{"frequency": _OUTPUT_FREQUENCY, "coupling": coupling}]
    return payload


def test_vcc_reproduces_the_program_output():
    """出力を写した入力の S と Delta が、出力の値に一致すること。"""
    parsed = FCEnvelopeInput.from_obj(_vcc_payload(_OUTPUT_VCC))
    huang_rhys = parsed.to_system().modes[0].huang_rhys

    assert huang_rhys == pytest.approx(0.038059, rel=1e-4)
    assert round(huang_rhys, 4) == 0.0381
    assert round(math.sqrt(2.0 * huang_rhys), 4) == 0.2759


def test_vcc_in_the_formal_name_agrees_with_the_alias():
    """同じ値を正式名で書いても同じ S になる。"""
    from_alias = FCEnvelopeInput.from_obj(_vcc_payload(_OUTPUT_VCC))
    from_formal = FCEnvelopeInput.from_obj(
        _vcc_payload(-0.3, coupling_unit="10^-4 hartree/(bohr*sqrt(m_e))")
    )

    assert from_formal.to_system() == from_alias.to_system()


def test_the_sign_of_v_does_not_matter():
    """V の符号は S に効かない。"""
    negative = FCEnvelopeInput.from_obj(_vcc_payload([-0.3, "10^-4 a.u."]))
    positive = FCEnvelopeInput.from_obj(_vcc_payload([0.3, "10^-4 a.u."]))

    assert negative.to_system() == positive.to_system()


def test_vcc_and_delta_agree():
    """Delta = V / sqrt(eps^3) が同じエンベロープを与える（`docs/theory/vcc.md` の表）。"""
    delta = 0.5
    canonical_v = delta * math.sqrt(1200.0**3)  # (cm^-1)^{3/2}
    in_au = canonical_v / units.VCC_UNIT_KIND.resolve("a.u.").factor

    from_delta = FCEnvelopeInput.from_obj(_payload("delta", delta))
    from_vcc = FCEnvelopeInput.from_obj(_payload("vcc", [in_au, "a.u."]))

    assert from_vcc.to_system().modes[0].huang_rhys == pytest.approx(
        from_delta.to_system().modes[0].huang_rhys, rel=1e-14
    )
    expected = _envelope(from_delta).density
    np.testing.assert_allclose(
        _envelope(from_vcc).density,
        expected,
        rtol=0.0,
        atol=1e-12 * float(expected.max()),
    )


def test_vcc_refuses_an_energy_unit():
    """V の欄にエネルギーの単位を書くと、未知の単位として拒否される（ADR-0077）。"""
    with pytest.raises(UnsupportedUnitError, match="vibronic coupling constant"):
        FCEnvelopeInput.from_obj(_vcc_payload([-0.3, "eV"]))


@pytest.mark.parametrize(
    ("convention", "coupling"),
    [("lambda", [300.0, "cm^-1"]), ("vcc", [-0.3, "a.u."])],
)
@pytest.mark.parametrize("frequency", [0.0, -500.0])
def test_a_non_positive_frequency_is_reported_before_the_conversion(
    convention, coupling, frequency
):
    """振動数で割る流儀でも、0 や負の振動数はモードの位置を添えた誤りになる。"""
    payload = _payload(convention, 0.0)
    payload["modes"] = [
        {"frequency": 1200.0, "coupling": coupling},
        {"frequency": frequency, "coupling": coupling},
    ]
    parsed = FCEnvelopeInput.from_obj(payload)

    with pytest.raises(InvalidInputError, match=r"modes\[1\]: frequency must be positive"):
        parsed.to_system()
