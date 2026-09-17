"""結果クラス。純粋なデータ容器であり、I/O も描画も行わない。

エンベロープ F(E)（`EnvelopeResult`）と離散 FC 因子（`LinesResult`）の
2 系統があり、どちらも入力エコー・診断値・来歴を自身に抱える。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from .models import Conditions, VibrationalMode

__all__ = [
    "Diagnostics",
    "EnvelopeResult",
    "FCLine",
    "FCLineDiagnostics",
    "LinesResult",
    "ModeTransition",
]


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
class EnvelopeResult:
    """Franck-Condon エンベロープの計算結果。"""

    energy: np.ndarray
    """(M,) float64, cm^-1, 単調増加。E = 0 が ZPL。"""

    density: np.ndarray
    """(M,) float64, 1/cm^-1。確率密度なので int F dE = 1。"""

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
    density_unit: str = "1/cm^-1"


@dataclass(frozen=True, slots=True)
class ModeTransition:
    """1 モードの振動量子数の変化 n_alpha -> m_alpha。"""

    mode_index: int
    """`LinesResult.modes` における位置。"""

    initial: int
    """始状態の振動量子数 n_alpha。"""

    final: int
    """終状態の振動量子数 m_alpha。"""


@dataclass(frozen=True, slots=True)
class FCLine:
    """離散的な振電遷移 1 本。"""

    energy: float
    """E = -sum_alpha (m_alpha - n_alpha) eps_alpha [cm^-1]。E = 0 が ZPL。"""

    fc_factor: float
    """FC 因子 prod_alpha |<m_alpha|U(g_alpha)|n_alpha>|^2（無次元）。"""

    weight: float
    """熱占有を掛けた重み prod_alpha P(n_alpha) * FC_alpha。全遷移にわたる総和は 1。"""

    transitions: tuple[ModeTransition, ...]
    """n_alpha = m_alpha = 0 のモードは含めない。空タプルなら ZPL。"""


@dataclass(frozen=True, slots=True)
class FCLineDiagnostics:
    """離散 FC 因子の数値品質。エンベロープ側の `Diagnostics` とは指標が異なる。"""

    n_lines: int
    """保持した線の本数。"""

    captured_weight: float
    """保持した線の重みの総和。理論上の総和 1 のうち拾えた割合。"""

    mean_energy: float
    """保持した線による <E> [cm^-1]。収束していれば -lambda に一致する。"""

    min_mode_completeness: float
    """モードごとの sum_m FC_mn の最小値。梯子の打ち切りの指標（理論上は 1）。"""

    max_initial_quanta: int
    """列挙した始状態の振動量子数 n_alpha の最大値。"""

    max_final_quanta: int
    """行列を構成した終状態の振動量子数 m_alpha の最大値。"""

    beam_truncated: bool
    """モードの合成途中で `max_lines` により候補を打ち切ったか。True なら網羅的でない。"""

    recurrence_limited: bool
    """漸化式の数値的破綻を避けるために始状態 n_alpha を打ち切ったか。"""

    messages: tuple[str, ...] = ()
    """発報した警告の文言。"""


@dataclass(frozen=True, slots=True)
class LinesResult:
    """離散 FC 因子の計算結果。重みの降順（同じ重みならエネルギーの昇順）に並ぶ。"""

    lines: tuple[FCLine, ...]
    """保持した線。主要なものから順に並ぶ。"""

    modes: tuple[VibrationalMode, ...]
    """入力エコー（正準形）。"""

    temperature: float
    """T [K]。始状態の熱占有に効く。"""

    min_weight: float
    """この重み以上の線をすべて保持する（`beam_truncated` が False である限り網羅的）。"""

    max_lines: int
    """保持・列挙する線数の上限。"""

    reorganization_energy: float
    """lambda = sum_alpha S_alpha * epsilon_alpha [cm^-1]。"""

    diagnostics: FCLineDiagnostics
    """数値品質の診断値。"""

    fcenvelope_version: str
    """計算に用いたパッケージのバージョン。"""

    created_at: datetime
    """計算時刻（UTC、秒精度）。"""

    energy_unit: str = "cm^-1"

    @property
    def energies(self) -> np.ndarray:
        """(L,) float64, cm^-1。`lines` と同じ順序。"""
        return np.array([line.energy for line in self.lines], dtype=np.float64)

    @property
    def fc_factors(self) -> np.ndarray:
        """(L,) float64, 無次元。`lines` と同じ順序。"""
        return np.array([line.fc_factor for line in self.lines], dtype=np.float64)

    @property
    def weights(self) -> np.ndarray:
        """(L,) float64, 無次元。`lines` と同じ順序。"""
        return np.array([line.weight for line in self.lines], dtype=np.float64)
