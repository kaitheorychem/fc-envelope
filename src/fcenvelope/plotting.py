"""結果クラスの可視化。matplotlib への依存はこのモジュールに閉じ込める。"""

from __future__ import annotations

import base64
import io
import logging
import math
import os
import sys
import time
import warnings
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - 型注釈のためだけの import
    import matplotlib.axes
    import matplotlib.figure

import numpy as np

from .errors import InvalidInputError
from .io import load_any
from .logs import stage
from .models import VibrationalSystem
from .result import EnvelopeResult, LinesResult, Result

__all__ = [
    "DRAWERS",
    "plot_any",
    "plot_envelope",
    "plot_lines",
    "plot_modes",
    "plot_overlay",
    "show",
]

logger = logging.getLogger(__name__)

ENERGY_UNIT = "cm^-1"
"""軸ラベルに書く E の単位。計算側は常にこの単位しか扱わない（ADR-0047）。"""

DENSITY_UNIT = "1/cm^-1"
"""軸ラベルに書く F(E) の単位。"""

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


def _energy_axis(ax: "matplotlib.axes.Axes") -> None:
    """どの図でも共通の E 軸の体裁。"""
    ax.set_xlabel(f"$E$ / {_mathtext_unit(ENERGY_UNIT)}")
    ax.axvline(0.0, **_GUIDE)


def _finish(
    ax: "matplotlib.axes.Axes", *, title: str | None, labelled: bool
) -> None:
    """表題と凡例。どの描画関数でも同じなのでここにまとめる。"""
    if title is not None:
        ax.set_title(title)
    if labelled:
        ax.legend()


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
    _energy_axis(ax)
    ax.set_ylabel(f"$F(E)$ / {_mathtext_unit(DENSITY_UNIT)}")


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
    with stage(logger, f"plot envelope ({result.energy.size} points)"):
        figure, ax = _resolve_axes(ax)

        _draw_envelope(ax, result, label=label)
        ax.margins(x=0.0)
        _finish(ax, title=title, labelled=label is not None)

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
    with stage(logger, f"plot lines ({len(result.lines)} lines)"):
        figure, ax = _resolve_axes(ax)

        _draw_sticks(ax, result.energies, result.weights, label=label)
        _energy_axis(ax)
        ax.set_ylabel("weight")
        ax.axhline(0.0, **_GUIDE)
        _finish(ax, title=title, labelled=label is not None)

    return figure


MODE_HEIGHTS = ("g", "S")
"""`plot_modes` の縦軸に取れる量。どちらも無次元。"""


def plot_modes(
    system: VibrationalSystem,
    *,
    height: str = "g",
    ax: "matplotlib.axes.Axes | None" = None,
    label: str | None = None,
    title: str | None = None,
) -> "matplotlib.figure.Figure":
    """モードごとに、振動数 ω の位置へ結合の高さの棒を立てて `Figure` を返す。

    縦軸は `height="g"` なら g = sqrt(S)、`"S"` なら Huang-Rhys 因子 S。系は S しか
    持たない（g の符号は物理的に意味を持たない）ので、g は常に正で描く。結果から描く
    ときは `plot_modes(result.system)` とする。横軸は E ではなく ω なので、E = 0 の
    案内線は引かない。
    """
    if height not in MODE_HEIGHTS:
        raise InvalidInputError(f"height must be one of {MODE_HEIGHTS} (got {height!r})")

    with stage(logger, f"plot modes ({len(system.modes)} modes)"):
        figure, ax = _resolve_axes(ax)

        huang_rhys = system.huang_rhys
        heights = np.sqrt(huang_rhys) if height == "g" else huang_rhys
        _draw_sticks(ax, system.frequencies, heights, label=label)
        ax.set_xlabel(rf"$\omega$ / {_mathtext_unit(ENERGY_UNIT)}")
        ax.set_ylabel(f"${height}$")
        ax.axhline(0.0, **_GUIDE)
        ax.set_xlim(left=0.0)
        _finish(ax, title=title, labelled=label is not None)

    return figure


def _warn_on_mismatch(envelope: EnvelopeResult, lines: LinesResult) -> None:
    """同じ系・同じ温度の結果どうしでないなら、重ねる前に知らせる。

    利用者への発報（`warnings`）と、何が起きたかの記録（ログ）の両方に出す。宛先が
    違うだけで同じ出来事なので、文言は 1 つにして 1 箇所で書く（ADR-0052）。
    """
    if envelope.system != lines.system:
        message = (
            "the envelope and the line list were computed for different systems; "
            "the sticks do not decompose this envelope"
        )
    elif envelope.temperature != lines.temperature:
        message = (
            f"temperature mismatch: the envelope is at "
            f"{envelope.temperature:g} K but the line list is at "
            f"{lines.temperature:g} K; the sticks do not decompose this envelope"
        )
    else:
        return
    warnings.warn(message, stacklevel=3)
    logger.warning("%s", message)


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

    縦軸は 1 本だけで、単位は F(E) と同じ 1/cm^-1。線の重み w は規格化した線形状の
    頂点値 L(0)（`Broadening.peak_height`。ガウス型なら 1/(sigma*sqrt(2pi))）を
    掛けて描く。これは「その線が F(E) に立てる山の高さそのもの」であり、F(E) は線を
    線形状で畳んで足し上げたものなので（`docs/theory/fc-factor.md`）、
    2 つの縦軸を勝手な比率で並べる場合と違って棒と曲線の高さを直接比べられる。
    孤立した線では棒の先端が曲線の山に一致し、sigma の中に何本も密集する
    ところでは曲線が棒より高くなる。線形状は `envelope` の条件から取る。

    線が密集して棒が潰れる系では `magnify` で棒だけを拡大できる。倍率は
    凡例に `(×N)` として出るので、拡大したことが図の上で失われない。

    横軸は `envelope` の E 窓に合わせる。窓の外に立つ線は描かれない。
    """
    if not magnify > 0.0:
        raise InvalidInputError(f"magnify must be positive (got {magnify})")

    _warn_on_mismatch(envelope, lines)

    with stage(
        logger,
        f"plot overlay ({envelope.energy.size} points, {len(lines.lines)} lines)",
    ):
        figure, ax = _resolve_axes(ax)

        # 頂点値の式は線形状が持つ（ADR-0034）。ここは種類を知らなくてよい。
        scale = magnify * envelope.broadening.peak_height()
        if lines_label is not None and magnify != 1.0:
            lines_label = rf"{lines_label} ($\times${magnify:g})"

        _draw_envelope(
            ax, envelope, label=envelope_label, color=ENVELOPE_COLOR, zorder=2.2
        )
        _draw_sticks(
            ax,
            lines.energies,
            lines.weights * scale,
            label=lines_label,
            color=LINES_COLOR,
            zorder=2.1,
        )
        ax.axhline(0.0, **_GUIDE)

        ax.margins(x=0.0)
        ax.set_xlim(float(envelope.energy[0]), float(envelope.energy[-1]))
        _finish(
            ax,
            title=title,
            labelled=envelope_label is not None or lines_label is not None,
        )

    return figure


#: 描画関数に共通の署名。表に載るのはこの形の関数だけで、`plot_any` はこの 3 つの
#: キーワードだけを通す。`**kwargs: Any` で素通しにすると、表の要素が同じ形を
#: していることが型から消える。
Drawer = Callable[..., "matplotlib.figure.Figure"]

#: 結果の型 -> 描画。種類を足すときはここに 1 行足す（ADR-0049）。
#: 重ね描きは表に載せない。種類ごとの処理ではなく「エンベロープと線」という特定の
#: 組み合わせに対する処理だからである。
DRAWERS: dict[type, Drawer] = {
    EnvelopeResult: plot_envelope,
    LinesResult: plot_lines,
}


def plot_any(
    result: Result,
    *,
    ax: "matplotlib.axes.Axes | None" = None,
    label: str | None = None,
    title: str | None = None,
) -> "matplotlib.figure.Figure":
    """結果の種類を見て描画する。引数は `plot_envelope` / `plot_lines` と同じ。"""
    try:
        draw = DRAWERS[type(result)]
    except KeyError as exc:
        raise InvalidInputError(f"no way to draw a {type(result).__name__}") from exc
    return draw(result, ax=ax, label=label, title=title)


NON_INTERACTIVE_BACKENDS = frozenset({"agg", "cairo", "pdf", "pgf", "ps", "svg", "template"})
"""窓を開けない matplotlib のバックエンド。ここで `plt.show()` を呼んでも何も出ない。"""


def opens_a_window() -> bool:
    """いまの matplotlib のバックエンドで `plt.show()` が図を出せるか。

    画面のない環境では matplotlib が自動で `agg` に落ちるので、その判定に使う。
    """
    import matplotlib.pyplot as plt

    return plt.get_backend().lower() not in NON_INTERACTIVE_BACKENDS


KITTY_QUERY = b"\033_Gi=31,s=1,v=1,a=q,t=d,f=24;AAAA\033\\"
"""kitty graphics protocol に対応しているかを端末に尋ねる列。1x1 画素の画像を
検証だけさせる（`a=q`）ので、画面には何も出ない。"""

DEVICE_ATTRIBUTES = b"\033[c"
"""どの端末も答える問い合わせ（DA1）。答えがここまでに来なければ非対応とみなす。"""

KITTY_TIMEOUT = 0.5
"""端末の答えを待つ上限の秒数。DA1 すら返さない端末で止まらないための保険。

tmux の中では DA1 を tmux 自身が答えてしまうので送らない。対応していない端末の外では
この秒数だけ待ってから窓に回る。"""

TERMINAL_SIZE = 0.5
"""端末に出すとき、窓の幅・高さに対する図の大きさの上限の割合。作図スクリプトの
`SHOW_SIZE` と同じ。"""

TERMINAL_DPI = 110
"""端末が画素数を返さないときの解像度。作図スクリプトの `SHOW_DPI` と同じ。"""


def in_tmux() -> bool:
    """tmux の中か。tmux は画像の列を素通しさせないので、包んで渡す必要がある。"""
    return bool(os.environ.get("TMUX"))


def _passthrough(sequence: bytes) -> bytes:
    """tmux の中なら、外の端末へ届くように包む。tmux 側で allow-passthrough が要る。

    作図スクリプトの `passthrough` と同じ。
    """
    if not in_tmux():
        return sequence
    return b"\033Ptmux;" + sequence.replace(b"\033", b"\033\033") + b"\033\\"


def kitty_terminal() -> bool:
    """標準入出力の先の端末が kitty graphics protocol で画像を出せるか。

    作図スクリプトは標準出力が端末かどうかだけで決める（ADR-0061）が、そちらは画像
    ファイルが必ず残る。`show` は端末に出せなければ窓に回したいので、端末に実際に
    尋ねる（ADR-0084）。問い合わせの後ろに DA1 を続けて送り、DA1 の答えより先に
    画像の答えが来れば対応している。SSH の先でも同じように働く。

    tmux の中では問い合わせを包んで外の端末へ届ける。tmux は外の端末の答えを中へ
    渡すが、DA1 には tmux 自身が即座に答えるので順序の判定に使えない。そこで DA1 は
    送らず、画像の答えが来るのを `KITTY_TIMEOUT` まで待つ。tmux 側で
    allow-passthrough が切られていれば問い合わせは届かず、窓に回る（ADR-0085）。
    """
    try:
        import select
        import termios
        import tty
    except ImportError:  # Windows
        return False
    try:
        stdin, stdout = sys.stdin.fileno(), sys.stdout.fileno()
        if not (os.isatty(stdin) and os.isatty(stdout)):
            return False
        saved = termios.tcgetattr(stdin)
    except (OSError, ValueError, AttributeError, termios.error):
        # 標準入出力が差し替えられて fileno を持たない（pytest の捕捉など）場合も含む。
        return False

    tmux = in_tmux()
    reply = b""
    try:
        tty.setcbreak(stdin)  # 答えを 1 バイトずつ読み、画面に出さない
        sys.stdout.flush()
        os.write(
            stdout, _passthrough(KITTY_QUERY) + (b"" if tmux else DEVICE_ATTRIBUTES)
        )
        deadline = time.monotonic() + KITTY_TIMEOUT
        while (left := deadline - time.monotonic()) > 0:
            ready, _, _ = select.select([stdin], [], [], left)
            if not ready:
                break
            reply += os.read(stdin, 1024)
            if b"\033[?" in reply and reply.endswith(b"c"):
                break
            if tmux and b"\033_Gi=31;" in reply and reply.endswith(b"\033\\"):
                break
    finally:
        termios.tcsetattr(stdin, termios.TCSAFLUSH, saved)
    answer = reply.split(b"\033[?", 1)[0]
    return b"\033_Gi=31;OK" in answer


def _terminal_size() -> tuple[int, int, int, int]:
    """端末の窓の (行数, 桁数, 画素幅, 画素高さ)。分からない値は 0。"""
    try:
        import fcntl
        import struct
        import termios

        packed = fcntl.ioctl(sys.stdout, termios.TIOCGWINSZ, b"\0" * 8)
    except (ImportError, OSError, ValueError, AttributeError):
        return 0, 0, 0, 0
    return struct.unpack("HHHH", packed)


def _to_terminal(figure: "matplotlib.figure.Figure") -> None:
    """kitty graphics protocol で端末に直に出す。作図スクリプトの `show` と同じ出し方。

    図は窓の幅と高さの `TERMINAL_SIZE` 倍に収まる大きさで描く。窓の画素数が分かれば
    解像度をそこから逆算して端末側で縮小させず（ADR-0061）、分からなければ
    `TERMINAL_DPI` で描いて行数だけ指定する。tmux の中では画像の後ろで tmux の
    カーソルが動かないので、画像の高さぶん改行する（ADR-0085）。
    """
    rows, columns, xpixel, ypixel = _terminal_size()
    width, height = figure.get_size_inches()
    if rows and columns and xpixel and ypixel:
        dpi = TERMINAL_SIZE * min(xpixel / width, ypixel / height)
        lines = math.ceil(height * dpi / (ypixel / rows))
        placement = ""
    else:
        dpi = TERMINAL_DPI
        lines = max(1, round(rows * TERMINAL_SIZE)) if rows else 1
        placement = f"r={lines}," if rows else ""
    tmux = in_tmux()
    if tmux:
        placement += "C=1,"  # カーソルは下の改行で動かす

    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=dpi)
    payload = base64.standard_b64encode(buffer.getvalue())

    sys.stdout.flush()
    out, first = sys.stdout.buffer, True
    while payload:  # 制御データは先頭のみ、以降は m= だけ
        head, payload = payload[:4096], payload[4096:]
        control = f"a=T,f=100,q=2,{placement}" if first else ""
        out.write(
            _passthrough(
                b"\033_G" + f"{control}m={int(bool(payload))}".encode()
                + b";" + head + b"\033\\"
            )
        )
        first = False
    out.write(b"\n" * (lines if tmux else 1))
    out.flush()


def _default_figure(
    results: "list[Result]", *, modes: bool
) -> "matplotlib.figure.Figure":
    """結果の並びから、既定の見た目の図を 1 枚描く。組み合わせの規則は `script` と同じ。

    1 つなら種類に応じた図、エンベロープと線リストを 1 つずつなら重ね描き、`modes`
    なら結合の図（結果は 1 つ）。
    """
    if modes:
        if len(results) != 1:
            raise InvalidInputError(
                f"modes takes exactly one result (got {len(results)}); "
                "the modes of an envelope and of its line list are the same"
            )
        return plot_modes(results[0].system)
    if len(results) == 1:
        return plot_any(results[0])

    envelopes = [item for item in results if isinstance(item, EnvelopeResult)]
    line_lists = [item for item in results if isinstance(item, LinesResult)]
    if len(results) != 2 or len(envelopes) != 1 or len(line_lists) != 1:
        found = ", ".join(type(item).__name__ for item in results)
        raise InvalidInputError(
            "overlaying takes exactly one EnvelopeResult and one LinesResult, "
            f"in either order (got {found or 'nothing'})"
        )
    return plot_overlay(envelopes[0], line_lists[0])


def show(
    *results: "Result | str | os.PathLike[str]",
    modes: bool = False,
    terminal: bool | None = None,
    block: bool | None = None,
) -> "matplotlib.figure.Figure":
    """結果を既定の見た目で描き、端末か窓に出す。描いた `Figure` を返す。

    ちょっと見るための口で、図のつまみは持たない（ADR-0084）。見た目を詰めるなら作図
    スクリプトか `plot_*` を使う。結果は計算した結果そのものでも、結果ファイルのパスでも
    よい。組み合わせの規則は `fcenvelope script` と同じで、1 つならその種類の図、
    エンベロープと線リストを 1 つずつなら重ね描き（順序は問わない）、`modes=True` なら
    その結果が使ったモードの結合の図になる。

    出し先は `terminal` で決まる。`None`（既定）なら、端末が kitty graphics protocol に
    対応していれば端末へ、そうでなければ `plt.show()` の窓へ出す。`True` / `False` で
    端末 / 窓に固定できる。端末に出した図は pyplot から外す（後の `plt.show()` で窓に
    出てこない）が、返した `Figure` はそのまま保存などに使える。

    `block` は窓に出すときだけ `plt.show` にそのまま渡す。既定では窓を閉じるまで戻らない。
    """
    loaded = [
        item if isinstance(item, (EnvelopeResult, LinesResult)) else load_any(item)
        for item in results
    ]
    figure = _default_figure(loaded, modes=modes)

    import matplotlib.pyplot as plt

    if terminal if terminal is not None else kitty_terminal():
        _to_terminal(figure)
        plt.close(figure)
    else:
        plt.show(block=block)
    return figure
