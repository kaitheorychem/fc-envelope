"""テスト全体で共有する設定とヘルパー。"""

from __future__ import annotations

import warnings

import matplotlib
import pytest

matplotlib.use("Agg")

from fcenvelope import (
    Broadening,
    EnergyGrid,
    EnvelopeResult,
    LinesResult,
    Selection,
    VibrationalMode,
    compute_envelope,
    compute_fc_lines,
)
from fcenvelope.errors import NumericalQualityWarning


def conditions(
    *,
    temperature: float = 300.0,
    sigma: float = 150.0,
    gamma: float = 0.0,
    e_min: float = -4000.0,
    e_max: float = 1000.0,
    de: float = 5.0,
) -> dict:
    """`compute_envelope` へ渡す条件一式（ADR-0035 の 3 節）。"""
    return {
        "temperature": temperature,
        "broadening": Broadening(sigma=sigma, gamma=gamma),
        "grid": EnergyGrid(e_min=e_min, e_max=e_max, de=de),
    }


def compute_quietly(modes: list[VibrationalMode], **kwargs) -> EnvelopeResult:
    """品質警告を抑制して計算する（警告そのものは診断値で検証する）。"""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NumericalQualityWarning)
        return compute_envelope(modes, **kwargs)


def lines_quietly(modes: list[VibrationalMode], **kwargs) -> LinesResult:
    """品質警告を抑制して離散 FC 因子を計算する。

    `selection` のフィールドは直接キーワードでも受ける（テストの見通しのため）。
    """
    fields = {
        key: kwargs.pop(key)
        for key in ("min_weight", "max_lines", "max_quanta")
        if key in kwargs
    }
    if fields:
        kwargs["selection"] = Selection(**fields)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NumericalQualityWarning)
        return compute_fc_lines(modes, **kwargs)


def moments(result: EnvelopeResult) -> tuple[float, float, float]:
    """出力配列から (面積, <E>, Var(E)) を数値積分で求める。"""
    de = result.grid.de
    weight = result.density * de
    area = float(weight.sum())
    mean = float((result.energy * weight).sum())
    variance = float((((result.energy - mean) ** 2) * weight).sum())
    return area, mean, variance


@pytest.fixture
def single_mode() -> list[VibrationalMode]:
    return [VibrationalMode(frequency=1200.0, huang_rhys=0.25)]


@pytest.fixture
def multi_mode() -> list[VibrationalMode]:
    return [
        VibrationalMode(frequency=1200.0, huang_rhys=0.25),
        VibrationalMode(frequency=450.0, huang_rhys=0.64),
        VibrationalMode(frequency=180.0, huang_rhys=1.5),
    ]


@pytest.fixture
def wide_conditions() -> dict:
    """モーメント検証用に、窓の取りこぼしが無視できる広い条件。"""
    return conditions(temperature=300.0, sigma=150.0, e_min=-12000.0, e_max=12000.0, de=2.0)


@pytest.fixture
def input_payload() -> dict:
    """`docs/dev/spec/interface.md`「ファイル形式 / 入力」のスキーマ。"""
    return {
        "schema_version": 2,
        "frequency_unit": "cm^-1",
        "coupling_convention": "g",
        "modes": [
            {"frequency": 1200.0, "coupling": 0.5},
            {"frequency": 450.0, "coupling": 0.8},
        ],
        "temperature": 300.0,
        "broadening": {"sigma": 150.0, "gamma": 0.0},
        "grid": {"e_min": -4000.0, "e_max": 1000.0, "de": 5.0},
        "selection": {"min_weight": 0.0001, "max_lines": 10000, "max_quanta": None},
    }
