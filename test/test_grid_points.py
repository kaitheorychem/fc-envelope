"""全域グリッドの取り方（`grid.points`、ADR-0070）。

`n` を直接書く道と、`de` から決める道の 2 つがある。どちらで書いても最後に残るのは
解決済みの (n_fft, de) の組で、窓 `e_min` / `e_max` は切り出しの範囲でしかない。
"""

from __future__ import annotations

import copy

import pytest
from conftest import compute_quietly

from fcenvelope import Broadening, EnergyGrid
from fcenvelope.errors import InvalidInputError
from fcenvelope.inputs import FCEnvelopeInput

WINDOW = {"e_min": -4000.0, "e_max": 1000.0}


def _grid(payload: dict, points: dict) -> EnergyGrid:
    """入力ファイルの `grid.points` を差し替えて、計算用のグリッドまで通す。"""
    data = copy.deepcopy(payload)
    data["grid"] = {**WINDOW, "points": points}
    return FCEnvelopeInput.from_obj(data).to_grid()


# --- n を直接書く ---


def test_n_fixes_the_count_and_the_full_span_is_the_window():
    """`n` 指定では全域幅が窓ちょうど 2 * e_half になり、dE がそこから決まる。"""
    grid = EnergyGrid.from_points(**WINDOW, n=4096)

    assert grid.n_fft == 4096
    assert grid.e_half == 4000.0
    assert grid.full_span == pytest.approx(8000.0, rel=1e-15)
    assert grid.de == pytest.approx(8000.0 / 4096, rel=1e-15)


def test_n_must_be_a_power_of_two():
    """FFT の基数なので、2 の冪でない点数はその場で止まる。"""
    with pytest.raises(InvalidInputError, match="power of two"):
        EnergyGrid.from_points(**WINDOW, n=3000)


def test_n_of_one_is_rejected():
    with pytest.raises(InvalidInputError, match="power of two"):
        EnergyGrid.from_points(**WINDOW, n=1)


# --- de から決める ---


def test_de_rounds_the_count_up_to_a_power_of_two():
    """`de` 指定では dE は書いたとおりで、点数がそれを満たす最小の 2 の冪になる。"""
    grid = EnergyGrid.from_spacing(**WINDOW, de=5.0)

    assert grid.de == 5.0
    assert grid.n_fft == 2048  # ceil(8000 / 5) = 1600 -> 2048
    assert grid.full_span == 2048 * 5.0


def test_shift_keeps_the_span_and_refines_the_spacing():
    """`shift` は全域幅を保ったまま点数を 2 倍にし、刻みを半分にする。"""
    base = EnergyGrid.from_spacing(**WINDOW, de=5.0)
    shifted = EnergyGrid.from_spacing(**WINDOW, de=5.0, shift=2)

    assert shifted.full_span == base.full_span
    assert shifted.n_fft == base.n_fft * 4
    assert shifted.de == base.de / 4 == 1.25


def test_shift_zero_is_the_plain_de_specification():
    assert EnergyGrid.from_spacing(**WINDOW, de=5.0, shift=0) == EnergyGrid.from_spacing(
        **WINDOW, de=5.0
    )


def test_a_negative_shift_is_rejected():
    """粗くしたいなら大きい de を書く。冪を下げる道は用意しない。"""
    with pytest.raises(InvalidInputError, match="non-negative"):
        EnergyGrid.from_spacing(**WINDOW, de=5.0, shift=-1)


# --- 値の型そのものの不変条件 ---


def test_the_full_grid_must_cover_the_window():
    """点数と間隔を直接渡す道でも、全域グリッドが窓を覆っていることを要求する。"""
    with pytest.raises(InvalidInputError, match="cover the window"):
        EnergyGrid(e_min=-4000.0, e_max=1000.0, de=1.0, n_fft=1024)


def test_n_fft_must_be_a_power_of_two():
    with pytest.raises(InvalidInputError, match="power of two"):
        EnergyGrid(e_min=-4000.0, e_max=1000.0, de=5.0, n_fft=1600)


# --- 入力ファイルの側 ---


def test_the_input_file_takes_n(input_payload):
    grid = _grid(input_payload, {"n": 4096})

    assert grid.n_fft == 4096
    assert grid.de == pytest.approx(8000.0 / 4096, rel=1e-15)


def test_the_input_file_takes_de_and_shift(input_payload):
    grid = _grid(input_payload, {"de": 5.0, "shift": 1})

    assert grid.n_fft == 4096
    assert grid.de == 2.5
    assert grid.full_span == 2048 * 5.0


@pytest.mark.parametrize("points", [{}, {"n": 4096, "de": 5.0}])
def test_exactly_one_way_must_be_written(input_payload, points):
    with pytest.raises(InvalidInputError, match="exactly one"):
        _grid(input_payload, points)


def test_shift_cannot_ride_along_with_n(input_payload):
    with pytest.raises(InvalidInputError, match="shift applies to de only"):
        _grid(input_payload, {"n": 4096, "shift": 1})


def test_the_grid_unit_applies_to_de_only(input_payload):
    """`de` は `grid.unit` で読まれ、`n` と `shift` は無次元のまま。"""
    data = copy.deepcopy(input_payload)
    data["grid"] = {"e_min": -0.5, "e_max": 0.125, "unit": "eV", "points": {"n": 4096}}
    grid = FCEnvelopeInput.from_obj(data).to_grid()

    assert grid.n_fft == 4096
    assert grid.de == pytest.approx(2.0 * grid.e_half / 4096, rel=1e-15)


# --- 計算まで通したときの見え方 ---


def test_shift_only_refines_the_sampling(multi_mode):
    """`shift` は覆う範囲を変えないので、エイリアシングの指標は動かない。

    動くのは刻みと点数だけである。端の折り返しを減らしたいときに回すつまみでは
    ない（ADR-0070）。
    """
    broadening = Broadening(sigma=150.0)
    base = compute_quietly(
        multi_mode,
        temperature=300.0,
        broadening=broadening,
        grid=EnergyGrid.from_spacing(**WINDOW, de=5.0),
    )
    shifted = compute_quietly(
        multi_mode,
        temperature=300.0,
        broadening=broadening,
        grid=EnergyGrid.from_spacing(**WINDOW, de=5.0, shift=1),
    )

    assert shifted.diagnostics.edge_intensity_ratio == pytest.approx(
        base.diagnostics.edge_intensity_ratio, rel=1e-9
    )
    assert shifted.diagnostics.n_fft == base.diagnostics.n_fft * 2
    assert shifted.energy.size > base.energy.size


@pytest.mark.parametrize(
    "grid",
    [
        EnergyGrid.from_points(**WINDOW, n=4096),
        EnergyGrid.from_spacing(**WINDOW, de=5.0, shift=1),
    ],
)
def test_zero_stays_on_the_grid_either_way(single_mode, grid):
    """E = 0（ZPL）がグリッド点に乗ることは、どちらの書き方でも変わらない。"""
    result = compute_quietly(
        single_mode,
        temperature=300.0,
        broadening=Broadening(sigma=150.0),
        grid=grid,
    )

    assert float(abs(result.energy).min()) == pytest.approx(0.0, abs=1e-9)
    assert result.diagnostics.total_area == pytest.approx(1.0, abs=1e-9)
