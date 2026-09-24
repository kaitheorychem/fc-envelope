"""離散 FC 因子: 平行移動演算子の行列要素、線の列挙、診断値算出。

理論は `docs/theory/fc-factor.md` の式そのもの。平行移動された調和振動子の
振動状態間の FC 因子を、平行移動演算子 U(g) = exp(g(a^dagger - a)) の行列要素の
漸化式

    sqrt(n+1) <m|U|n+1> = sqrt(m) <m-1|U|n> - g <m|U|n>

から求め、二乗して FC_mn = |<m|U|n>|^2 とする。初期条件は

    <m|U|0> = exp(-g^2 / 2) g^m / sqrt(m!)

符号規約は `envelope.py` のエンベロープと同一で、反転しない。E = 0 が ZPL であり、
振動量子を正味 k 個生成する線は E = -k * eps_alpha（負側）に立つ。多モードでは

    E = -sum_alpha (m_alpha - n_alpha) eps_alpha

線の重みは始状態の熱占有 P(n_alpha) を掛けた

    w = prod_alpha P(n_alpha) * FC_{m_alpha n_alpha}

とする。この w を中心 E・標準偏差 sigma のガウシアンで畳んで足し上げたものが
`compute_envelope` の F(E) に一致する（`docs/theory/time-ft.md` の rho(tau) の
母関数展開そのもの）。したがって全遷移にわたる w の総和は厳密に 1 である。
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timezone

import numpy as np
from scipy.special import gammaln

from .errors import report_quality
from .logs import stage
from .models import Selection, VibrationalMode, VibrationalSystem, validate_temperature
from .physics import K_B_CM, boltzmann_populations
from .result import FCLine, FCLineDiagnostics, LinesResult, ModeTransition, Provenance
from .version import __version__

__all__ = [
    "MAX_QUANTA_PER_MODE",
    "compute_fc_lines",
    "displacement_matrix",
    "fc_factor_matrix",
]

logger = logging.getLogger(__name__)

#: `max_quanta` を省略したときに自動決定が到達しうる 1 モードあたりの量子数の上限。
MAX_QUANTA_PER_MODE = 200

#: 漸化式の数値的破綻を検出する許容値（`_stable_fc_matrix` を参照）。
RECURRENCE_TOLERANCE = 1e-8

# --- 診断値の警告閾値 ---
MIN_CAPTURED_WEIGHT = 0.9


def displacement_matrix(g: float, m_max: int, n_max: int) -> np.ndarray:
    """平行移動演算子の行列要素 <m|U(g)|n> を (m_max+1, n_max+1) で返す。

    `docs/theory/fc-factor.md` の漸化式を n について前進させる。初期条件の
    g^m / sqrt(m!) は m が大きいと桁溢れしうるため対数で組み立てる。
    """
    if m_max < 0 or n_max < 0:
        raise ValueError(f"m_max and n_max must be non-negative (got {m_max}, {n_max})")
    if g < 0.0:
        raise ValueError(f"g must be non-negative (got {g}); FC factors do not depend on its sign")

    elements = np.zeros((m_max + 1, n_max + 1), dtype=float)
    quanta = np.arange(m_max + 1)

    # <m|U|0> = exp(-g^2/2) g^m / sqrt(m!)。g = 0 では m > 0 がすべて 0 になる。
    if g == 0.0:
        elements[0, 0] = 1.0
    else:
        elements[:, 0] = np.exp(
            -0.5 * g * g + quanta * math.log(g) - 0.5 * gammaln(quanta + 1.0)
        )

    sqrt_m = np.sqrt(quanta.astype(float))
    lowered = np.empty(m_max + 1, dtype=float)
    for n in range(n_max):
        # lowered[m] = <m-1|U|n>（m = 0 では 0）
        lowered[0] = 0.0
        lowered[1:] = elements[:-1, n]
        elements[:, n + 1] = (sqrt_m * lowered - g * elements[:, n]) / math.sqrt(n + 1)
    return elements


def fc_factor_matrix(huang_rhys: float, m_max: int, n_max: int = 0) -> np.ndarray:
    """FC 因子 FC_mn = |<m|U(g)|n>|^2 を (m_max+1, n_max+1) で返す。

    引数は正準量 S（Huang-Rhys 因子）で受ける。g = sqrt(S) であり、g の符号は
    FC 因子に効かない（`docs/adr/0003-canonical-coupling-huang-rhys.md`）。
    """
    if huang_rhys < 0.0:
        raise ValueError(f"huang_rhys must be non-negative (got {huang_rhys})")
    elements = displacement_matrix(math.sqrt(huang_rhys), m_max, n_max)
    return elements * elements


def _max_initial_quanta(frequency: float, temperature: float, min_population: float) -> int:
    """P(n) >= min_population を満たす最大の n。T = 0 では 0。"""
    if temperature == 0.0:
        return 0
    ratio = math.exp(-frequency / (K_B_CM * temperature))
    if ratio <= 0.0:
        return 0
    threshold = min_population / (1.0 - ratio)
    if threshold >= 1.0:
        return 0
    return max(0, int(math.floor(math.log(threshold) / math.log(ratio))))


def _initial_final_guess(huang_rhys: float, n_max: int) -> int:
    """終状態の量子数の初期見積り。足りなければ倍々に伸ばす。"""
    spread = math.sqrt(huang_rhys + n_max + 1.0)
    return max(8, int(math.ceil(huang_rhys + n_max + 6.0 * spread)))


class _ModeCandidates:
    """1 モードについて閾値を超える (n, m) と、その FC 因子・重みの表。"""

    __slots__ = (
        "completeness",
        "entries",
        "max_final",
        "max_initial",
        "max_weight",
        "recurrence_limited",
    )

    def __init__(
        self,
        entries: list[tuple[int, int, float, float]],
        max_weight: float,
        completeness: float,
        max_initial: int,
        max_final: int,
        recurrence_limited: bool,
    ) -> None:
        #: (n, m, FC_mn, P(n) * FC_mn) を重みの降順に並べたもの。
        self.entries = entries
        #: 閾値の前後によらない P(n) * FC_mn の最大値。合成時の上界に使う。
        self.max_weight = max_weight
        self.completeness = completeness
        self.max_initial = max_initial
        self.max_final = max_final
        self.recurrence_limited = recurrence_limited


def _stable_fc_matrix(
    huang_rhys: float, n_max: int, min_weight: float, cap: int
) -> tuple[np.ndarray, float, bool]:
    """数値的に信頼できる範囲の FC 行列を返す。

    2 つの打ち切りを列和 sum_m FC_mn で見分ける。FC_mn は非負なので、

    * **m の打ち切り**（梯子が短い）では正の項を落とすだけなので列和は 1 を下回る。
      これは `m_max` を倍々に伸ばして解消する。
    * **漸化式の数値的破綻**（g が大きく n も大きい領域で sqrt(m) <m-1|U|n> と
      g <m|U|n> が桁落ちする）では誤差が二乗されて正の側に積み上がるため、
      列和が 1 を上回る。`m_max` を伸ばしても解消しないので、破綻が始まる直前の
      列までで n を打ち切る。

    Returns:
        (FC 行列 (m_max+1, n_used+1), 列和の最小値, 漸化式による n の打ち切りの有無)。
    """
    m_max = min(_initial_final_guess(huang_rhys, n_max), cap)
    while True:
        factors = fc_factor_matrix(huang_rhys, m_max, n_max)
        sums = factors.sum(axis=0)
        broken = np.nonzero(sums > 1.0 + RECURRENCE_TOLERANCE)[0]
        recurrence_limited = bool(broken.size)
        if recurrence_limited:
            # 列 0 は閉じた式そのもので必ず 1 以下だが、念のため 1 列は残す。
            limit = max(1, int(broken[0]))
            factors = factors[:, :limit]
            sums = sums[:limit]
        completeness = float(np.min(sums))
        if completeness > 1.0 - min_weight or m_max >= cap:
            return factors, completeness, recurrence_limited
        m_max = min(2 * m_max, cap)


def _mode_candidates(
    mode: VibrationalMode,
    temperature: float,
    min_weight: float,
    max_quanta: int | None,
) -> _ModeCandidates:
    """1 モードの候補表を作る。"""
    cap = MAX_QUANTA_PER_MODE if max_quanta is None else max_quanta
    n_max = min(_max_initial_quanta(mode.frequency, temperature, min_weight), cap)
    factors, completeness, recurrence_limited = _stable_fc_matrix(
        mode.huang_rhys, n_max, min_weight, cap
    )
    m_max, n_used = factors.shape[0] - 1, factors.shape[1] - 1
    populations = boltzmann_populations(mode.frequency, temperature, n_used)

    weights = factors * populations[np.newaxis, :]
    finals, initials = np.nonzero(weights >= min_weight)
    entries = [
        (int(n), int(m), float(factors[m, n]), float(weights[m, n]))
        for m, n in zip(finals, initials, strict=True)
    ]
    # 重みの降順。合成時の早期打ち切りと、beam の打ち切りがこの順序に依存する。
    entries.sort(key=lambda entry: (-entry[3], entry[1] - entry[0]))
    return _ModeCandidates(
        entries, float(weights.max()), completeness, n_used, m_max, recurrence_limited
    )


def compute_fc_lines(
    system: VibrationalSystem,
    *,
    temperature: float,
    selection: Selection = Selection(),
) -> LinesResult:
    """離散 FC 因子と対応するエネルギーを、重みの大きい順に列挙する。

    `min_weight` 以上の線を**すべて**返す（`diagnostics.beam_truncated` が
    False である限り）。1 モードあたりの寄与 P(n) * FC_mn は 1 以下なので、
    完成した線の重みは途中経過の積を超えない。したがってモードを 1 つずつ
    合成しながら閾値で枝刈りしても、閾値以上の線を取りこぼさない。

    Args:
        system: 正準形の振動モードの集まり。
        temperature: T [K]。始状態の熱占有に効く。0 なら始状態は振動基底状態のみ。
        selection: どの線を保持するかのつまみ。既定値は `Selection` にある。
            `max_quanta` を省略すると、打ち切り残差が `min_weight` を下回るまで
            梯子を自動で伸ばす（上限 `MAX_QUANTA_PER_MODE`）。

    Returns:
        線の列と、計算条件・診断値・来歴を含む結果クラス。
    """
    validate_temperature(temperature)
    # 節目はこの 1 組だけにする。モードごと・線ごとの記録は取らない（ADR-0052）。
    with stage(
        logger,
        f"fc lines: {len(system.modes)} modes, T={temperature:g} K, "
        f"min_weight={selection.min_weight:g}",
    ):
        lines, measured, strongest_weight = _enumerate(system, temperature, selection)
    logger.info(
        "fc lines: %d lines, captured=%.6g", measured.n_lines, measured.captured_weight
    )
    messages = report_quality(
        _quality_messages(selection, measured, strongest_weight=strongest_weight)
    )

    return LinesResult(
        system=system,
        temperature=temperature,
        selection=selection,
        lines=lines,
        diagnostics=replace(measured, messages=messages),
        provenance=Provenance(
            fcenvelope_version=__version__,
            created_at=datetime.now(timezone.utc).replace(microsecond=0),
        ),
    )


def _enumerate(
    system: VibrationalSystem, temperature: float, selection: Selection
) -> tuple[tuple[FCLine, ...], FCLineDiagnostics, float]:
    """数値計算。保持した線と、そこから読める測定値、到達しうる最大の重みを返す。

    測定値は判定を含まない生の数値で、閾値との突き合わせは `_quality_messages` が
    行う（ADR-0048）。**返す `FCLineDiagnostics` の `messages` は空**で、判定の結果は
    組み立ての段階で `dataclasses.replace` により入る。測定値の入れ物を別に作らない
    のは、フィールド名を 2 箇所に書くことになるからである（ADR-0036）。
    """
    modes = system.modes
    min_weight = selection.min_weight
    max_lines = selection.max_lines

    candidates = [
        _mode_candidates(mode, temperature, min_weight, selection.max_quanta)
        for mode in modes
    ]

    # suffix_bound[i] = 未処理のモード i.. が到達しうる重みの積の上限。
    # これを掛けて枝刈りすることで、途中経過の本数を抑えたまま網羅性を保てる。
    # モードごとの選択は独立なので suffix_bound[0] は最大の線の重みそのものになる。
    suffix_bound = [1.0] * (len(modes) + 1)
    for index in reversed(range(len(modes))):
        suffix_bound[index] = suffix_bound[index + 1] * candidates[index].max_weight

    lines, beam_truncated = _combine(
        candidates, modes, suffix_bound, min_weight=min_weight, max_lines=max_lines
    )

    if len(lines) > max_lines:
        lines = lines[:max_lines]
        beam_truncated = True

    captured = float(sum(line.weight for line in lines))
    mean_energy = (
        float(sum(line.weight * line.energy for line in lines) / captured)
        if captured > 0.0
        else 0.0
    )
    measured = FCLineDiagnostics(
        n_lines=len(lines),
        captured_weight=captured,
        mean_energy=mean_energy,
        min_mode_completeness=min(candidate.completeness for candidate in candidates),
        max_initial_quanta=max(candidate.max_initial for candidate in candidates),
        max_final_quanta=max(candidate.max_final for candidate in candidates),
        beam_truncated=beam_truncated,
        recurrence_limited=any(candidate.recurrence_limited for candidate in candidates),
    )
    return tuple(lines), measured, suffix_bound[0]


def _combine(
    candidates: Sequence[_ModeCandidates],
    modes: Sequence[VibrationalMode],
    suffix_bound: Sequence[float],
    *,
    min_weight: float,
    max_lines: int,
) -> tuple[list[FCLine], bool]:
    """モードを 1 つずつ合成して線を組み立てる。"""
    # (重み, FC 因子, エネルギー, 遷移)
    partials: list[tuple[float, float, float, tuple[ModeTransition, ...]]] = [(1.0, 1.0, 0.0, ())]
    beam_truncated = False

    for index, (candidate, mode) in enumerate(zip(candidates, modes, strict=True)):
        bound = suffix_bound[index + 1]
        combined: list[tuple[float, float, float, tuple[ModeTransition, ...]]] = []
        for weight, factor, energy, transitions in partials:
            for initial, final, mode_factor, mode_weight in candidate.entries:
                # entries は重みの降順なので、ここで落ちたら以降もすべて落ちる。
                if weight * mode_weight * bound < min_weight:
                    break
                combined.append(
                    (
                        weight * mode_weight,
                        factor * mode_factor,
                        energy - (final - initial) * mode.frequency,
                        transitions
                        if initial == 0 and final == 0
                        else (*transitions, ModeTransition(index, initial, final)),
                    )
                )
        combined.sort(key=lambda item: (-item[0], item[2]))
        if len(combined) > max_lines:
            combined = combined[:max_lines]
            beam_truncated = True
        partials = combined
        if not partials:
            break

    lines = [
        FCLine(energy=energy, fc_factor=factor, weight=weight, transitions=transitions)
        for weight, factor, energy, transitions in partials
    ]
    return lines, beam_truncated


def _quality_messages(
    selection: Selection, measured: FCLineDiagnostics, *, strongest_weight: float
) -> tuple[str, ...]:
    """診断値の判定。閾値を超えた項目について警告文言を組み立てる。

    文言は「何が起きたか」に加えて「どう直すか」を持つので、雛形に押し込めず手書きで
    残す（ADR-0036）。発報そのものは `errors.report_quality` が行う。`mean_energy`
    だけは診断値として記録するのみで、判定には使わない。
    """
    min_weight = selection.min_weight
    max_lines = selection.max_lines
    n_lines = measured.n_lines
    captured_weight = measured.captured_weight
    min_mode_completeness = measured.min_mode_completeness
    max_initial_quanta = measured.max_initial_quanta
    max_final_quanta = measured.max_final_quanta
    beam_truncated = measured.beam_truncated
    recurrence_limited = measured.recurrence_limited

    messages: list[str] = []

    if n_lines == 0:
        messages.append(
            f"no transition reaches min_weight = {min_weight:g}: the strongest "
            f"possible line has weight {strongest_weight:.3g}. Set min_weight "
            "below it, or use fewer modes; with many thermally active modes the "
            "spectrum is spread over too many lines to be described discretely."
        )
    elif captured_weight < MIN_CAPTURED_WEIGHT:
        messages.append(
            f"captured_weight = {captured_weight:.4g} < {MIN_CAPTURED_WEIGHT:g}: "
            f"the {n_lines} retained lines account for only part of the spectrum. "
            "Lower min_weight (and raise max_lines) to keep more of it."
        )
    if beam_truncated:
        messages.append(
            f"the line list was truncated at max_lines = {max_lines}: lines above "
            f"min_weight = {min_weight:g} are missing. Raise min_weight "
            "to get an exhaustive list, or raise max_lines."
        )
    if abs(1.0 - min_mode_completeness) >= min_weight:
        messages.append(
            f"min_mode_completeness = {min_mode_completeness:.6g} deviates from 1 by at "
            f"least min_weight = {min_weight:g} at max_final_quanta = "
            f"{max_final_quanta}: the vibrational ladder is truncated. Raise max_quanta."
        )
    if recurrence_limited:
        messages.append(
            f"the initial state was capped at max_initial_quanta = {max_initial_quanta} "
            "because the matrix-element recurrence loses accuracy at large g and n; "
            "thermally populated states above it are missing. Use a coarser "
            "min_weight or a lower temperature."
        )

    return tuple(messages)
