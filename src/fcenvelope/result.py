"""結果クラス。純粋なデータ容器であり、I/O も描画も行わない。

エンベロープ F(E)（`EnvelopeResult`）と離散 FC 因子（`LinesResult`）の
2 系統があり、どちらも入力エコー・診断値・来歴を自身に抱える。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from .models import Broadening, EnergyGrid, Selection, VibrationalSystem

__all__ = [
    "AnyDiagnostics",
    "Diagnostics",
    "EnvelopeResult",
    "FCLine",
    "FCLineDiagnostics",
    "LinesResult",
    "ModeTransition",
    "Provenance",
    "Result",
]


@dataclass(frozen=True, slots=True)
class Provenance:
    """来歴。計算がいつ、どの版で行われたか。

    物理量でも計算条件でもなく、計算を行った時点で確定する（ADR-0008）。実行場所
    などを記録するならここに足す（ADR-0046）。
    """

    fcenvelope_version: str
    """計算に用いたパッケージのバージョン。"""

    created_at: datetime
    """計算時刻（UTC、秒精度）。"""


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
    """全域グリッド端の密度 / ピーク密度。エイリアシングの指標。

    名前の `intensity` はガウス型だけを扱っていた頃の名残で、指すのは密度である。
    """

    max_imaginary_ratio: float
    """max|Im F| / max|Re F|。rho の対称性の破れの指標。"""

    messages: tuple[str, ...] = ()
    """発報した警告の文言。"""


@dataclass(frozen=True, slots=True)
class EnvelopeResult:
    """Franck-Condon エンベロープの計算結果。

    持つのは計算で決まったものだけである（ADR-0047）。lambda は系から一意に決まる
    ので `system.reorganization_energy` から、単位はファイル形式の知識なので `io`
    から得る。
    """

    system: VibrationalSystem
    """入力エコー（正準形）。"""

    temperature: float
    """T [K]。系とは別の、測定の条件（ADR-0046）。"""

    broadening: Broadening
    """入力エコー。線形状。"""

    grid: EnergyGrid
    """入力エコー。エネルギーグリッド。"""

    energy: np.ndarray
    """(M,) float64, cm^-1, 単調増加。E = 0 が ZPL。"""

    density: np.ndarray
    """(M,) float64, 1/cm^-1。確率密度なので int F dE = 1。"""

    diagnostics: Diagnostics
    """数値品質の診断値。"""

    provenance: Provenance
    """来歴。"""


@dataclass(frozen=True, slots=True)
class ModeTransition:
    """1 モードの振動量子数の変化 n_alpha -> m_alpha。"""

    mode_index: int
    """`LinesResult.system.modes` における位置。"""

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
    """離散 FC 因子の計算結果。重みの降順（同じ重みならエネルギーの昇順）に並ぶ。

    `EnvelopeResult` と同じく、持つのは計算で決まったものだけである（ADR-0047）。
    """

    system: VibrationalSystem
    """入力エコー（正準形）。"""

    temperature: float
    """T [K]。始状態の熱占有に効く。"""

    selection: Selection
    """入力エコー。どの線を保持するかのつまみ。"""

    lines: tuple[FCLine, ...]
    """保持した線。主要なものから順に並ぶ。"""

    diagnostics: FCLineDiagnostics
    """数値品質の診断値。"""

    provenance: Provenance
    """来歴。"""

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


#: 結果クラスの全体。種類は 2 つで打ち止めではないが、増えるときは表に 1 行足す形に
#: なっている（ADR-0049）。`Any` で受けるとその 2 つしかないことが型から消えるので、
#: 種類によらず結果を扱う関数はこの別名を使う。
Result = EnvelopeResult | LinesResult

#: 診断値クラスの全体。指標は系統ごとに違うので共通の基底クラスは作らない（ADR-0046）。
AnyDiagnostics = Diagnostics | FCLineDiagnostics
