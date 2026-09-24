"""エンベロープ F(E): グリッド構成、rho(tau)、FFT、診断値算出。

理論は `docs/theory/time-ft.md` の式そのもの:

    F(E) = (1 / 2pi) * int dtau rho(tau) D(tau) exp(i E tau)

    rho(tau) = prod_alpha exp( -S_a (2 n_a + 1)
                               + S_a (n_a + 1) exp(+i eps_a tau)
                               + S_a n_a       exp(-i eps_a tau) )

D(tau) は線形状に由来する減衰因子で、その形は `Broadening` が持つ（ADR-0034）。
このモジュールは線形状の種類を知らない。ガウス型では D = exp(-sigma^2 tau^2 / 2)。

符号規約は反転しない。E = 0 が ZPL であり、振動量子を k 個生成する
サイドバンドは E = -k * eps_alpha（負側）に立つ。
"""

from __future__ import annotations

import logging
import math
from dataclasses import replace
from datetime import datetime, timezone

import numpy as np

from .errors import report_quality
from .logs import stage
from .models import Broadening, EnergyGrid, VibrationalSystem, validate_temperature
from .result import Diagnostics, EnvelopeResult, Provenance
from .version import __version__

__all__ = [
    "build_grids",
    "compute_envelope",
]

logger = logging.getLogger(__name__)

# --- 診断値の警告閾値（§7 の表） ---
# tau 窓の打ち切りの閾値だけは線形状の側にある（`Broadening.MIN_TRUNCATION_INDICATOR`）。
MAX_EDGE_INTENSITY_RATIO = 1e-4
MAX_AREA_DEVIATION = 1e-6
MIN_WINDOW_CAPTURED_FRACTION = 0.99
MAX_IMAGINARY_RATIO = 1e-8


def build_grids(grid: EnergyGrid) -> tuple[np.ndarray, np.ndarray, int, float]:
    """FFT 標準順序の (energy, tau) グリッドと (N, d_tau) を構成する。

    0 対称な全域 E グリッド上で計算し、最後に窓へ切り出す。この取り方により
    出力の dE は `grid.de` ちょうどになり、E = 0 が必ずグリッド点に乗る。

    全域グリッドの (N, dE) は `EnergyGrid` が解決済みで持っている（ADR-0070）。
    ここでは 2 の冪への丸めも窓からの推定もしない。
    """
    de = grid.de
    n_fft = grid.n_fft
    d_tau = 2.0 * math.pi / (n_fft * de)

    index = np.arange(n_fft)
    signed = np.where(index < n_fft // 2, index, index - n_fft).astype(float)
    return signed * de, signed * d_tau, n_fft, d_tau


def _log_rho(
    tau: np.ndarray,
    system: VibrationalSystem,
    temperature: float,
) -> np.ndarray:
    """ln rho(tau) をモードについてループ加算で構成する。

    全モード x 全 tau の外積は作らない（N = 2^17・200 モードで数百 MB になる）。
    """
    occupations = system.occupations(temperature)

    log_rho = np.zeros(tau.shape, dtype=np.complex128)
    for mode, n_alpha in zip(system.modes, occupations, strict=True):
        s_alpha = mode.huang_rhys
        if s_alpha == 0.0:
            continue
        phase = np.exp(1j * mode.frequency * tau)
        log_rho += (
            -s_alpha * (2.0 * n_alpha + 1.0)
            + s_alpha * (n_alpha + 1.0) * phase
            + s_alpha * n_alpha * phase.conjugate()
        )
    return log_rho


def compute_envelope(
    system: VibrationalSystem,
    *,
    temperature: float,
    broadening: Broadening,
    grid: EnergyGrid,
) -> EnvelopeResult:
    """Franck-Condon エンベロープ F(E) を計算する。

    Args:
        system: 正準形の振動モードの集まり。
        temperature: T [K]。始状態の熱占有に効く。
        broadening: 線形状。現在はガウス幅 sigma だけ。
        grid: エンベロープを標本する E 軸上の点列。

    Returns:
        窓へ切り出した F(E) と、計算条件・診断値・来歴を含む結果クラス。
    """
    validate_temperature(temperature)
    # 節目はこの 1 組だけにする。モードや tau 点ごとの記録は取らない（ADR-0052）。
    with stage(
        logger,
        f"envelope: {len(system.modes)} modes, T={temperature:g} K, "
        f"de={grid.de:g}, N={grid.n_fft}",
    ):
        energy, density, measured = _transform(system, temperature, broadening, grid)
    logger.info(
        "envelope: %d points, N_fft=%d, dE=%.9g, full span=%.9g, "
        "area=%.9g, captured=%.6g",
        energy.size,
        grid.n_fft,
        grid.de,
        grid.full_span,
        measured.total_area,
        measured.window_captured_fraction,
    )
    messages = report_quality(_quality_messages(broadening, grid, measured))

    return EnvelopeResult(
        system=system,
        temperature=temperature,
        broadening=broadening,
        grid=grid,
        energy=energy,
        density=density,
        diagnostics=replace(measured, messages=messages),
        provenance=Provenance(
            fcenvelope_version=__version__,
            created_at=datetime.now(timezone.utc).replace(microsecond=0),
        ),
    )


def _transform(
    system: VibrationalSystem,
    temperature: float,
    broadening: Broadening,
    grid: EnergyGrid,
) -> tuple[np.ndarray, np.ndarray, Diagnostics]:
    """数値計算。窓へ切り出した (energy, density) と、そこから読める測定値を返す。

    測定値は判定を含まない生の数値で、閾値との突き合わせは `_quality_messages` が
    行う（ADR-0048）。**返す `Diagnostics` の `messages` は空**で、判定の結果は
    組み立ての段階で `dataclasses.replace` により入る。測定値の入れ物を別に作らない
    のは、フィールド名を 2 箇所に書くことになるからである（ADR-0036）。
    """
    energy_full, tau, n_fft, d_tau = build_grids(grid)

    log_rho = _log_rho(tau, system, temperature)
    m_tau = np.exp(log_rho + broadening.log_damping(tau))

    # F(E_j) = (1 / dE) * ifft(M)_j （tau・E ともに FFT 標準順序のため位相因子は不要）
    spectrum_full = np.fft.ifft(m_tau) / grid.de

    real_full = spectrum_full.real
    peak = float(np.max(np.abs(real_full)))
    max_imag = float(np.max(np.abs(spectrum_full.imag)))
    max_imaginary_ratio = max_imag / peak if peak > 0.0 else 0.0

    energy_full = np.fft.fftshift(energy_full)
    real_full = np.ascontiguousarray(np.fft.fftshift(real_full))

    total_area = float(np.sum(real_full) * grid.de)
    edge_intensity = max(abs(float(real_full[0])), abs(float(real_full[-1])))
    edge_intensity_ratio = edge_intensity / peak if peak > 0.0 else 0.0

    # 端点は de の整数倍にスナップされる。丸め誤差でグリッド点を落とさないよう緩衝を置く。
    tol = 1e-9 * grid.de
    window = (energy_full >= grid.e_min - tol) & (energy_full <= grid.e_max + tol)
    energy = np.ascontiguousarray(energy_full[window])
    density = np.ascontiguousarray(real_full[window])

    window_area = float(np.sum(density) * grid.de)
    window_captured_fraction = window_area / total_area if total_area != 0.0 else 0.0

    tau_max = math.pi / grid.de
    measured = Diagnostics(
        d_tau=d_tau,
        tau_max=tau_max,
        # 名前はガウス型の名残。減衰因子そのもので測る形への一般化は ADR-0038（提案）。
        sigma_tau_max=broadening.truncation_indicator(tau_max),
        total_area=total_area,
        window_captured_fraction=window_captured_fraction,
        edge_intensity_ratio=edge_intensity_ratio,
        max_imaginary_ratio=max_imaginary_ratio,
    )
    return energy, density, measured


def _quality_messages(
    broadening: Broadening, grid: EnergyGrid, measured: Diagnostics
) -> tuple[str, ...]:
    """診断値の判定。閾値を超えた項目について警告文言を組み立てる。

    文言は「何が起きたか」に加えて「どう直すか」を持つので、雛形に押し込めず手書きで
    残す（ADR-0036）。発報そのものは `errors.report_quality` が行う。

    `grid` を受け取るのは、端の折り返しの助言が窓ではなく全域グリッドを名指しする
    ためである（ADR-0071）。閾値の持ち主である `broadening` と同じく、助言が名指しする
    値の出どころを引数で受ける形になっている。
    """
    sigma_tau_max = measured.sigma_tau_max
    edge_intensity_ratio = measured.edge_intensity_ratio
    total_area = measured.total_area
    window_captured_fraction = measured.window_captured_fraction
    max_imaginary_ratio = measured.max_imaginary_ratio

    messages: list[str] = []

    if sigma_tau_max < broadening.MIN_TRUNCATION_INDICATOR:
        messages.append(
            f"sigma*tau_max = {sigma_tau_max:.3g} < "
            f"{broadening.MIN_TRUNCATION_INDICATOR:g}: "
            f"the tau window (tau_max = pi/de, de = {grid.de:.6g}) is truncated "
            "before the damping completes; ringing is likely. Use de smaller than "
            "sigma/2; a larger n or shift at the same window does the same."
        )
    if edge_intensity_ratio > MAX_EDGE_INTENSITY_RATIO:
        messages.append(
            f"edge_intensity_ratio = {edge_intensity_ratio:.3g} > "
            f"{MAX_EDGE_INTENSITY_RATIO:g}: spectral weight reaches the edge of the "
            f"full grid at |E| = {0.5 * grid.full_span:.6g} and is aliased back. "
            f"That edge is set by the full grid n_fft * de = {grid.full_span:.6g}, "
            f"not by the window, which reaches |E| = {grid.e_half:.6g}: widen it with a "
            "wider e_min/e_max, or a smaller de, which rounds the point count up to "
            "the next power of two. A larger n or shift only refines the grid."
        )
    if abs(1.0 - total_area) > MAX_AREA_DEVIATION:
        messages.append(
            f"total_area = {total_area:.12g} deviates from 1 by more than "
            f"{MAX_AREA_DEVIATION:g}: the normalization or the grid construction is wrong."
        )
    if window_captured_fraction < MIN_WINDOW_CAPTURED_FRACTION:
        messages.append(
            f"window_captured_fraction = {window_captured_fraction:.4g} < "
            f"{MIN_WINDOW_CAPTURED_FRACTION:g}: the output window "
            f"[{grid.e_min:.6g}, {grid.e_max:.6g}] misses part of the envelope; here "
            "it is the window itself that is too narrow. Widen e_min/e_max."
        )
    if max_imaginary_ratio > MAX_IMAGINARY_RATIO:
        messages.append(
            f"max_imaginary_ratio = {max_imaginary_ratio:.3g} > {MAX_IMAGINARY_RATIO:g}: "
            "F(E) should be real; the symmetry rho(-tau) = conj(rho(tau)) is broken."
        )

    return tuple(messages)
