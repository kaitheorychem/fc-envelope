"""FC Envelope: Franck-Condon エンベロープ F(E) と離散 FC 因子の計算・永続化・可視化。

公開 API は系統ごとに「計算・保存・読み込み・描画」の自由関数 4 つ。結果クラスは
純粋なデータ容器であり、I/O と描画の責務を持たない。

    >>> from fcenvelope import Broadening, EnergyGrid, VibrationalMode, compute_envelope
    >>> modes = [VibrationalMode(frequency=1200.0, huang_rhys=0.25)]
    >>> result = compute_envelope(
    ...     modes,
    ...     temperature=300.0,
    ...     broadening=Broadening(sigma=150.0),
    ...     grid=EnergyGrid(e_min=-4000.0, e_max=1000.0, de=5.0),
    ... )
    >>> round(float(result.diagnostics.total_area), 9)
    1.0

スペクトル全体ではなく主要な離散遷移だけを見たい場合は `compute_fc_lines` を使う。

    >>> from fcenvelope import compute_fc_lines
    >>> lines = compute_fc_lines(modes, temperature=0.0)
    >>> [(line.energy, round(line.fc_factor, 6)) for line in lines.lines[:2]]
    [(0.0, 0.778801), (-1200.0, 0.1947)]
"""

from __future__ import annotations

from .envelope import compute_envelope
from .errors import (
    FCEnvelopeError,
    InvalidInputError,
    NumericalQualityWarning,
    SchemaVersionError,
    UnsupportedUnitError,
)
from .io import load_envelope, load_lines, save_envelope, save_lines
from .lines import compute_fc_lines, fc_factor_matrix
from .models import (
    Broadening,
    CouplingConvention,
    EnergyGrid,
    FCEnvelopeInput,
    ModeSpec,
    Selection,
    VibrationalMode,
)
from .plotting import plot_envelope, plot_lines, plot_overlay
from .result import (
    EnvelopeDiagnostics,
    EnvelopeResult,
    FCLine,
    LinesDiagnostics,
    LinesResult,
    ModeTransition,
)
from .version import __version__

__all__ = [
    # 公開 API: エンベロープ F(E)
    "compute_envelope",
    "save_envelope",
    "load_envelope",
    "plot_envelope",
    # 公開 API: 離散 FC 因子
    "compute_fc_lines",
    "save_lines",
    "load_lines",
    "plot_lines",
    "fc_factor_matrix",
    # 公開 API: 2 つの表現の重ね描き
    "plot_overlay",
    # データモデル
    "Broadening",
    "CouplingConvention",
    "EnergyGrid",
    "EnvelopeDiagnostics",
    "EnvelopeResult",
    "FCEnvelopeInput",
    "FCLine",
    "LinesDiagnostics",
    "LinesResult",
    "ModeSpec",
    "ModeTransition",
    "Selection",
    "VibrationalMode",
    # 例外・警告
    "FCEnvelopeError",
    "InvalidInputError",
    "NumericalQualityWarning",
    "SchemaVersionError",
    "UnsupportedUnitError",
    "__version__",
]
