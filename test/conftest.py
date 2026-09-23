"""テスト全体で共有する設定とヘルパー。"""

from __future__ import annotations

import os
import subprocess
import sys
import warnings
from pathlib import Path

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
    VibrationalSystem,
    compute_envelope,
    compute_fc_lines,
)
from fcenvelope.errors import NumericalQualityWarning


def compute_quietly(
    system: VibrationalSystem,
    *,
    temperature: float,
    broadening: Broadening,
    grid: EnergyGrid,
) -> EnvelopeResult:
    """品質警告を抑制して計算する（警告そのものは診断値で検証する）。"""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NumericalQualityWarning)
        return compute_envelope(
            system, temperature=temperature, broadening=broadening, grid=grid
        )


def lines_quietly(
    system: VibrationalSystem, *, temperature: float, **selection: object
) -> LinesResult:
    """品質警告を抑制して離散 FC 因子を計算する。つまみは `Selection` に束ねる。"""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NumericalQualityWarning)
        return compute_fc_lines(
            system, temperature=temperature, selection=Selection(**selection)
        )


def moments(result: EnvelopeResult) -> tuple[float, float, float]:
    """出力配列から (面積, <E>, Var(E)) を数値積分で求める。"""
    de = result.grid.de
    weight = result.density * de
    area = float(weight.sum())
    mean = float((result.energy * weight).sum())
    variance = float((((result.energy - mean) ** 2) * weight).sum())
    return area, mean, variance


@pytest.fixture
def single_mode() -> VibrationalSystem:
    return VibrationalSystem([VibrationalMode(frequency=1200.0, huang_rhys=0.25)])


@pytest.fixture
def multi_mode() -> VibrationalSystem:
    return VibrationalSystem(
        [
            VibrationalMode(frequency=1200.0, huang_rhys=0.25),
            VibrationalMode(frequency=450.0, huang_rhys=0.64),
            VibrationalMode(frequency=180.0, huang_rhys=1.5),
        ]
    )


@pytest.fixture
def input_payload() -> dict:
    """`docs/dev/spec/interface.md`「ファイル形式 / 入力」のスキーマ。

    テストはこれを JSON で書き出して入力ファイルにすることが多いが、それは辞書を
    書き出す手段が標準ライブラリに JSON しかない（`tomllib` は読むだけ）からで、
    入力の基本が JSON だという意味ではない。人が書く入力の基本は TOML で、文書の
    例もそちらで書く（ADR-0069）。書式が読んだ後に消えることは `test_toml_input.py`
    が確かめているので、書式に関わらないテストは JSON のままでよい。
    """
    return {
        "schema_version": 3,
        "frequency_unit": "cm^-1",
        "coupling_convention": "g",
        "modes": [
            {"frequency": 1200.0, "coupling": 0.5},
            {"frequency": 450.0, "coupling": 0.8},
        ],
        "temperature": 300.0,
        "broadening": {"sigma": 150.0},
        "grid": {"e_min": -4500.0, "e_max": 1000.0, "points": {"de": 4.0}},
    }


def run_script(script: Path, *arguments: str) -> subprocess.CompletedProcess:
    """生成されたスクリプトを、標準出力が端末でない状態で走らせる。"""
    return subprocess.run(
        [sys.executable, str(script), *arguments],
        capture_output=True,
        env={**os.environ, "MPLBACKEND": "Agg"},
        check=False,
    )
