"""FC Envelope: Franck-Condon エンベロープ F(E) の計算・永続化・可視化。

公開 API は自由関数 4 つ。結果クラスは純粋なデータ容器であり、I/O と描画の
責務を持たない。

    >>> from fcenvelope import Conditions, VibrationalMode, compute_envelope
    >>> modes = [VibrationalMode(frequency=1200.0, huang_rhys=0.25)]
    >>> conditions = Conditions(
    ...     temperature=300.0, sigma=150.0, e_min=-4000.0, e_max=1000.0, de=5.0
    ... )
    >>> result = compute_envelope(modes, conditions)
    >>> round(float(result.diagnostics.total_area), 9)
    1.0
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
from .io import load_result, save_result
from .models import (
    Conditions,
    CouplingConvention,
    FCEnvelopeInput,
    ModeSpec,
    VibrationalMode,
)
from .plotting import plot_result
from .result import Diagnostics, FCEnvelopeResult
from .version import __version__

__all__ = [
    # 公開 API（§9）
    "compute_envelope",
    "save_result",
    "load_result",
    "plot_result",
    # データモデル
    "Conditions",
    "CouplingConvention",
    "Diagnostics",
    "FCEnvelopeInput",
    "FCEnvelopeResult",
    "ModeSpec",
    "VibrationalMode",
    # 例外・警告
    "FCEnvelopeError",
    "InvalidInputError",
    "NumericalQualityWarning",
    "SchemaVersionError",
    "UnsupportedUnitError",
    "__version__",
]
