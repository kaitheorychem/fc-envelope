"""結果クラス。純粋なデータ容器であり、I/O も描画も行わない。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from .models import Conditions, VibrationalMode

__all__ = ["Diagnostics", "FCEnvelopeResult"]


@dataclass(frozen=True, slots=True)
class Diagnostics:
    """数値品質の診断値。出力ファイルだけを見て信頼可否を判定するための情報。"""

    n_fft: int
    """FFT 点数 N。"""

    d_tau: float
    """tau グリッド間隔 [cm]。"""

    tau_max: float
    """tau の絶対値の最大 = pi / de [cm]。"""

    sigma_tau_max: float
    """sigma * tau_max。打ち切りリンギングの指標。"""

    total_area: float
    """全域グリッドでの sum(F) * de。理論上は厳密に 1。"""

    window_captured_fraction: float
    """切り出し窓内に残った面積の割合。"""

    edge_intensity_ratio: float
    """全域グリッド端の強度 / ピーク強度。エイリアシングの指標。"""

    max_imaginary_ratio: float
    """max|Im F| / max|Re F|。rho の対称性の破れの指標。"""

    messages: tuple[str, ...] = ()
    """発報した警告の文言。"""


@dataclass(frozen=True, slots=True)
class FCEnvelopeResult:
    """Franck-Condon エンベロープの計算結果。"""

    energy: np.ndarray
    """(M,) float64, cm^-1, 単調増加。E = 0 が ZPL。"""

    intensity: np.ndarray
    """(M,) float64, 1/cm^-1。"""

    modes: tuple[VibrationalMode, ...]
    """入力エコー（正準形）。"""

    conditions: Conditions
    """入力エコー。"""

    reorganization_energy: float
    """lambda = sum_alpha S_alpha * epsilon_alpha [cm^-1]。"""

    diagnostics: Diagnostics
    """数値品質の診断値。"""

    fcenvelope_version: str
    """計算に用いたパッケージのバージョン。"""

    created_at: datetime
    """計算時刻（UTC、秒精度）。"""

    energy_unit: str = "cm^-1"
    intensity_unit: str = "1/cm^-1"
