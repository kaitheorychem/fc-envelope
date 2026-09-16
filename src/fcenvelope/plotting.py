"""結果クラスの可視化。matplotlib への依存はこのモジュールに閉じ込める。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - 型注釈のためだけの import
    import matplotlib.axes
    import matplotlib.figure

from .result import FCEnvelopeResult, FCLinesResult

__all__ = ["plot_fc_lines", "plot_result"]


def _mathtext_unit(unit: str) -> str:
    """`"cm^-1"` のような単位文字列を mathtext の指数表記にする。"""
    return unit.replace("^-1", r"$^{-1}$")


def plot_result(
    result: FCEnvelopeResult,
    *,
    ax: "matplotlib.axes.Axes | None" = None,
    label: str | None = None,
    title: str | None = None,
) -> "matplotlib.figure.Figure":
    """F(E) を描画し `Figure` を返す。ファイル保存は行わない。

    `ax` を渡せば複数条件を 1 枚に重ね描きできる。保存は呼び出し側の責務。
    """
    import matplotlib.pyplot as plt

    if ax is None:
        figure, ax = plt.subplots(figsize=(7.0, 4.2), layout="constrained")
    else:
        figure = ax.figure

    ax.plot(result.energy, result.intensity, label=label, linewidth=1.2)
    ax.set_xlabel(f"$E$ / {_mathtext_unit(result.energy_unit)}")
    ax.set_ylabel(f"$F(E)$ / {_mathtext_unit(result.intensity_unit)}")
    ax.axvline(0.0, color="0.7", linewidth=0.8, zorder=0)
    ax.margins(x=0.0)

    if title is not None:
        ax.set_title(title)
    if label is not None:
        ax.legend()

    return figure


def plot_fc_lines(
    result: FCLinesResult,
    *,
    ax: "matplotlib.axes.Axes | None" = None,
    label: str | None = None,
    title: str | None = None,
) -> "matplotlib.figure.Figure":
    """離散 FC 因子を棒スペクトルとして描画し `Figure` を返す。

    縦軸は熱占有を掛けた線強度（無次元）で、エンベロープ F(E)（1/cm^-1）とは
    次元が異なる。同じ軸に重ねる場合は縦軸の意味が変わる点に注意。
    """
    import matplotlib.pyplot as plt

    if ax is None:
        figure, ax = plt.subplots(figsize=(7.0, 4.2), layout="constrained")
    else:
        figure = ax.figure

    ax.vlines(
        result.energies,
        0.0,
        result.intensities,
        label=label,
        linewidth=1.2,
    )
    ax.set_xlabel(f"$E$ / {_mathtext_unit(result.energy_unit)}")
    ax.set_ylabel("line intensity")
    ax.axhline(0.0, color="0.7", linewidth=0.8, zorder=0)
    ax.axvline(0.0, color="0.7", linewidth=0.8, zorder=0)

    if title is not None:
        ax.set_title(title)
    if label is not None:
        ax.legend()

    return figure
