"""FC Envelope: Franck-Condon エンベロープ F(E) と離散 FC 因子の計算・永続化・可視化。

公開 API は系統ごとに「計算・保存・読み込み・描画」の自由関数 4 つ。結果クラスは
純粋なデータ容器であり、I/O と描画の責務を持たない。

    >>> from fcenvelope import Conditions, VibrationalMode, compute_envelope
    >>> modes = [VibrationalMode(frequency=1200.0, huang_rhys=0.25)]
    >>> conditions = Conditions(
    ...     temperature=300.0, sigma=150.0, e_min=-4000.0, e_max=1000.0, de=5.0
    ... )
    >>> result = compute_envelope(modes, conditions)
    >>> round(float(result.diagnostics.total_area), 9)
    1.0

スペクトル全体ではなく主要な離散遷移だけを見たい場合は `compute_fc_lines` を使う。

    >>> from fcenvelope import compute_fc_lines
    >>> lines = compute_fc_lines(modes, temperature=0.0)
    >>> [(line.energy, round(line.fc_factor, 6)) for line in lines.lines[:2]]
    [(0.0, 0.778801), (-1200.0, 0.1947)]
"""

from __future__ import annotations

from .core import compute_envelope
from .errors import (
    FCEnvelopeError,
    InvalidInputError,
    NumericalQualityWarning,
    SchemaVersionError,
    UnsupportedUnitError,
)
from .fcfactor import compute_fc_lines, fc_factor_matrix
from .io import load_fc_lines, load_result, save_fc_lines, save_result
from .models import (
    Conditions,
    CouplingConvention,
    FCEnvelopeInput,
    ModeSpec,
    VibrationalMode,
)
from .plotting import plot_fc_lines, plot_result
from .result import (
    Diagnostics,
    FCEnvelopeResult,
    FCLine,
    FCLineDiagnostics,
    FCLinesResult,
    ModeTransition,
)
from .version import __version__

__all__ = [
    # 公開 API: エンベロープ F(E)
    "compute_envelope",
    "save_result",
    "load_result",
    "plot_result",
    # 公開 API: 離散 FC 因子
    "compute_fc_lines",
    "save_fc_lines",
    "load_fc_lines",
    "plot_fc_lines",
    "fc_factor_matrix",
    # データモデル
    "Conditions",
    "CouplingConvention",
    "Diagnostics",
    "FCEnvelopeInput",
    "FCEnvelopeResult",
    "FCLine",
    "FCLineDiagnostics",
    "FCLinesResult",
    "ModeSpec",
    "ModeTransition",
    "VibrationalMode",
    # 例外・警告
    "FCEnvelopeError",
    "InvalidInputError",
    "NumericalQualityWarning",
    "SchemaVersionError",
    "UnsupportedUnitError",
    "__version__",
]
