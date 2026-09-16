"""結果クラスの可視化。matplotlib への依存はこのモジュールに閉じ込める。"""

from __future__ import annotations

import math
import warnings
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - 型注釈のためだけの import
    import matplotlib.axes
    import matplotlib.figure

from .errors import InvalidInputError
from .result import EnvelopeResult, LinesResult

__all__ = ["plot_envelope", "plot_lines", "plot_overlay"]

ENVELOPE_COLOR = "C0"
"""重ね描きでエンベロープ F(E) に割り当てる色。"""

LINES_COLOR = "C1"
"""重ね描きで離散 FC 因子に割り当てる色。"""

_GUIDE = {"color": "0.7", "linewidth": 0.8, "zorder": 0}


def _mathtext_unit(unit: str) -> str:
    """`"cm^-1"` のような単位文字列を mathtext の指数表記にする。"""
    return unit.replace("^-1", r"$^{-1}$")


def _resolve_axes(
    ax: "matplotlib.axes.Axes | None",
) -> "tuple[matplotlib.figure.Figure, matplotlib.axes.Axes]":
    """`ax` 省略時のみ既定サイズの Figure を起こす。"""
    if ax is not None:
        return ax.figure, ax

    import matplotlib.pyplot as plt

    return plt.subplots(figsize=(7.0, 4.2), layout="constrained")


def _gaussian_peak(sigma: float) -> float:
    """規格化ガウシアン G_sigma(0) = 1 / (sigma * sqrt(2 pi)) [1/cm^-1]。"""
    return 1.0 / (sigma * math.sqrt(2.0 * math.pi))


def _draw_envelope(
    ax: "matplotlib.axes.Axes",
    result: EnvelopeResult,
    *,
    label: str | None,
    color: str | None = None,
    zorder: float | None = None,
) -> None:
    """F(E) の曲線と軸ラベルを描く。凡例・表題は呼び出し側の責務。"""
    style: dict = {"linewidth": 1.2}
    if color is not None:
        style["color"] = color
    if zorder is not None:
        style["zorder"] = zorder

    ax.plot(result.energy, result.density, label=label, **style)
    ax.set_xlabel(f"$E$ / {_mathtext_unit(result.energy_unit)}")
    ax.set_ylabel(f"$F(E)$ / {_mathtext_unit(result.density_unit)}")


def _draw_sticks(
    ax: "matplotlib.axes.Axes",
    energies,
    heights,
    *,
    label: str | None,
    color: str | None = None,
    zorder: float | None = None,
) -> None:
    """線スペクトルを底辺 0 の棒として描く。縦軸の意味は呼び出し側が決める。"""
    style: dict = {"linewidth": 1.2}
    if color is not None:
        style["colors"] = color
    if zorder is not None:
        style["zorder"] = zorder

    ax.vlines(energies, 0.0, heights, label=label, **style)


def plot_envelope(
    result: EnvelopeResult,
    *,
    ax: "matplotlib.axes.Axes | None" = None,
    label: str | None = None,
    title: str | None = None,
) -> "matplotlib.figure.Figure":
    """F(E) を描画し `Figure` を返す。ファイル保存は行わない。

    `ax` を渡せば複数条件を 1 枚に重ね描きできる。保存は呼び出し側の責務。
    """
    figure, ax = _resolve_axes(ax)

    _draw_envelope(ax, result, label=label)
    ax.axvline(0.0, **_GUIDE)
    ax.margins(x=0.0)

    if title is not None:
        ax.set_title(title)
    if label is not None:
        ax.legend()

    return figure


def plot_lines(
    result: LinesResult,
    *,
    ax: "matplotlib.axes.Axes | None" = None,
    label: str | None = None,
    title: str | None = None,
) -> "matplotlib.figure.Figure":
    """離散 FC 因子を棒スペクトルとして描画し `Figure` を返す。

    縦軸は熱占有を掛けた重み（無次元）で、エンベロープ F(E)（1/cm^-1）とは
    次元が異なる。エンベロープと 1 枚に重ねる場合は `plot_overlay` を使う。
    """
    figure, ax = _resolve_axes(ax)

    _draw_sticks(ax, result.energies, result.weights, label=label)
    ax.set_xlabel(f"$E$ / {_mathtext_unit(result.energy_unit)}")
    ax.set_ylabel("line weight")
    ax.axhline(0.0, **_GUIDE)
    ax.axvline(0.0, **_GUIDE)

    if title is not None:
        ax.set_title(title)
    if label is not None:
        ax.legend()

    return figure


def _warn_on_mismatch(envelope: EnvelopeResult, lines: LinesResult) -> None:
    """同じ系・同じ温度の結果どうしでないなら、重ねる前に知らせる。"""
    if envelope.modes != lines.modes:
        warnings.warn(
            "the envelope and the line list were computed for different modes; "
            "the sticks do not decompose this envelope",
            stacklevel=3,
        )
    elif envelope.temperature != lines.temperature:
        warnings.warn(
            f"temperature mismatch: the envelope is at "
            f"{envelope.temperature:g} K but the line list is at "
            f"{lines.temperature:g} K; the sticks do not decompose this envelope",
            stacklevel=3,
        )


def plot_overlay(
    envelope: EnvelopeResult,
    lines: LinesResult,
    *,
    ax: "matplotlib.axes.Axes | None" = None,
    envelope_label: str | None = "envelope",
    lines_label: str | None = "FC lines",
    magnify: float = 1.0,
    title: str | None = None,
) -> "matplotlib.figure.Figure":
    """エンベロープ F(E) と離散 FC 因子を 1 枚に重ねて描画する。

    縦軸は 1 本だけで、単位は F(E) と同じ 1/cm^-1。重み w は幅 sigma の
    規格化ガウシアンの頂点 G_sigma(0) = 1/(sigma*sqrt(2pi)) を掛けて描く。
    これは「その線が F(E) に立てる山の高さそのもの」であり、F(E) は線を
    sigma で畳んで足し上げたものなので（`docs/theory/fc-factor.md`）、
    2 つの縦軸を勝手な比率で並べる場合と違って棒と曲線の高さを直接比べられる。
    孤立した線では棒の先端が曲線の山に一致し、sigma の中に何本も密集する
    ところでは曲線が棒より高くなる。sigma は `envelope` の条件から取る。

    線が密集して棒が潰れる系では `magnify` で棒だけを拡大できる。倍率は
    凡例に `(×N)` として出るので、拡大したことが図の上で失われない。

    横軸は `envelope` の E 窓に合わせる。窓の外に立つ線は描かれない。
    """
    if not magnify > 0.0:
        raise InvalidInputError(f"magnify must be positive (got {magnify})")

    _warn_on_mismatch(envelope, lines)

    figure, ax = _resolve_axes(ax)

    scale = magnify * _gaussian_peak(envelope.broadening.sigma)
    if lines_label is not None and magnify != 1.0:
        lines_label = rf"{lines_label} ($\times${magnify:g})"

    _draw_envelope(ax, envelope, label=envelope_label, color=ENVELOPE_COLOR, zorder=2.2)
    _draw_sticks(
        ax,
        lines.energies,
        lines.weights * scale,
        label=lines_label,
        color=LINES_COLOR,
        zorder=2.1,
    )
    ax.axhline(0.0, **_GUIDE)
    ax.axvline(0.0, **_GUIDE)

    ax.margins(x=0.0)
    ax.set_xlim(float(envelope.energy[0]), float(envelope.energy[-1]))

    if title is not None:
        ax.set_title(title)
    if envelope_label is not None or lines_label is not None:
        ax.legend()

    return figure
