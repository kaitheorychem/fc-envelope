"""エンベロープ F(E): グリッド構成、FFT、診断値算出。

理論は `docs/theory/time-ft.md` の式そのもの:

    F(E) = (1 / 2pi) * int dtau rho(tau) exp(i E tau - sigma^2 tau^2 / 2)

    rho(tau) = prod_alpha exp( -S_a (2 n_a + 1)
                               + S_a (n_a + 1) exp(+i eps_a tau)
                               + S_a n_a       exp(-i eps_a tau) )

符号規約は反転しない。E = 0 が ZPL であり、振動量子を k 個生成する
サイドバンドは E = -k * eps_alpha（負側）に立つ。
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Sequence
from datetime import datetime, timezone

import numpy as np

from .errors import NumericalQualityWarning
from .models import Conditions, VibrationalMode
from .physics import occupation_numbers, reorganization_energy
from .result import EnvelopeDiagnostics, EnvelopeResult
from .version import __version__

__all__ = [
    "build_grids",
    "compute_envelope",
]

# --- 診断値の警告閾値（§7 の表） ---
MIN_SIGMA_TAU_MAX = 6.0
MAX_EDGE_DENSITY_RATIO = 1e-4
MAX_AREA_DEVIATION = 1e-6
MIN_WINDOW_CAPTURED_FRACTION = 0.99
MAX_IMAGINARY_RATIO = 1e-8


def _next_pow2(value: int) -> int:
    """value 以上の最小の 2 のべき（最小 2）。"""
    if value <= 2:
        return 2
    return 1 << (value - 1).bit_length()


def build_grids(conditions: Conditions) -> tuple[np.ndarray, np.ndarray, int, float]:
    """FFT 標準順序の (energy, tau) グリッドと (N, d_tau) を構成する。

    0 対称な全域 E グリッド上で計算し、最後に窓へ切り出す。この取り方により
    出力の dE は指定した `de` ちょうどになり、E = 0 が必ずグリッド点に乗る。
    """
    de = conditions.de
    e_half = max(abs(conditions.e_min), abs(conditions.e_max))
    n_fft = _next_pow2(math.ceil(2.0 * e_half / de))
    d_tau = 2.0 * math.pi / (n_fft * de)

    index = np.arange(n_fft)
    signed = np.where(index < n_fft // 2, index, index - n_fft).astype(float)
    return signed * de, signed * d_tau, n_fft, d_tau


def _log_rho(
    tau: np.ndarray,
    modes: Sequence[VibrationalMode],
    temperature: float,
) -> np.ndarray:
    """ln rho(tau) をモードについてループ加算で構成する。

    全モード x 全 tau の外積は作らない（N = 2^17・200 モードで数百 MB になる）。
    """
    frequencies = np.array([mode.frequency for mode in modes], dtype=float)
    occupations = occupation_numbers(frequencies, temperature)

    log_rho = np.zeros(tau.shape, dtype=np.complex128)
    for mode, n_alpha in zip(modes, occupations, strict=True):
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
    modes: Sequence[VibrationalMode],
    conditions: Conditions,
) -> EnvelopeResult:
    """Franck-Condon エンベロープ F(E) を計算する。

    Args:
        modes: 正準表現の振動モード列（frequency [cm^-1], huang_rhys）。
        conditions: 温度・広がり・出力 E グリッドの指定。

    Returns:
        窓へ切り出した F(E) と、入力エコー・診断値・来歴を含む結果クラス。
    """
    modes = tuple(modes)
    energy_full, tau, n_fft, d_tau = build_grids(conditions)

    log_rho = _log_rho(tau, modes, conditions.temperature)
    damping = -0.5 * conditions.sigma**2 * tau**2
    m_tau = np.exp(log_rho + damping)

    # F(E_j) = (1 / dE) * ifft(M)_j （tau・E ともに FFT 標準順序のため位相因子は不要）
    spectrum_full = np.fft.ifft(m_tau) / conditions.de

    real_full = spectrum_full.real
    peak = float(np.max(np.abs(real_full)))
    max_imag = float(np.max(np.abs(spectrum_full.imag)))
    max_imaginary_ratio = max_imag / peak if peak > 0.0 else 0.0

    energy_full = np.fft.fftshift(energy_full)
    real_full = np.ascontiguousarray(np.fft.fftshift(real_full))

    total_area = float(np.sum(real_full) * conditions.de)
    edge_density = max(abs(float(real_full[0])), abs(float(real_full[-1])))
    edge_density_ratio = edge_density / peak if peak > 0.0 else 0.0

    # 端点は de の整数倍にスナップされる。丸め誤差でグリッド点を落とさないよう緩衝を置く。
    tol = 1e-9 * conditions.de
    window = (energy_full >= conditions.e_min - tol) & (energy_full <= conditions.e_max + tol)
    energy = np.ascontiguousarray(energy_full[window])
    density = np.ascontiguousarray(real_full[window])

    window_area = float(np.sum(density) * conditions.de)
    window_captured_fraction = window_area / total_area if total_area != 0.0 else 0.0

    tau_max = math.pi / conditions.de
    sigma_tau_max = conditions.sigma * tau_max

    messages = _quality_messages(
        sigma_tau_max=sigma_tau_max,
        edge_density_ratio=edge_density_ratio,
        total_area=total_area,
        window_captured_fraction=window_captured_fraction,
        max_imaginary_ratio=max_imaginary_ratio,
    )
    for message in messages:
        warnings.warn(message, NumericalQualityWarning, stacklevel=2)

    diagnostics = EnvelopeDiagnostics(
        n_fft=n_fft,
        d_tau=d_tau,
        tau_max=tau_max,
        sigma_tau_max=sigma_tau_max,
        total_area=total_area,
        window_captured_fraction=window_captured_fraction,
        edge_density_ratio=edge_density_ratio,
        max_imaginary_ratio=max_imaginary_ratio,
        messages=messages,
    )

    return EnvelopeResult(
        energy=energy,
        density=density,
        modes=modes,
        conditions=conditions,
        reorganization_energy=reorganization_energy(modes),
        diagnostics=diagnostics,
        fcenvelope_version=__version__,
        created_at=datetime.now(timezone.utc).replace(microsecond=0),
    )


def _quality_messages(
    *,
    sigma_tau_max: float,
    edge_density_ratio: float,
    total_area: float,
    window_captured_fraction: float,
    max_imaginary_ratio: float,
) -> tuple[str, ...]:
    """閾値を超えた診断値について警告文言を組み立てる。"""
    messages: list[str] = []

    if sigma_tau_max < MIN_SIGMA_TAU_MAX:
        messages.append(
            f"sigma*tau_max = {sigma_tau_max:.3g} < {MIN_SIGMA_TAU_MAX:g}: "
            "the tau window is truncated before the Gaussian damping completes; "
            "ringing is likely. Use de smaller than sigma/2."
        )
    if edge_density_ratio > MAX_EDGE_DENSITY_RATIO:
        messages.append(
            f"edge_density_ratio = {edge_density_ratio:.3g} > "
            f"{MAX_EDGE_DENSITY_RATIO:g}: spectral weight reaches the edge of the "
            "full grid and is aliased back. Widen e_min/e_max."
        )
    if abs(1.0 - total_area) > MAX_AREA_DEVIATION:
        messages.append(
            f"total_area = {total_area:.12g} deviates from 1 by more than "
            f"{MAX_AREA_DEVIATION:g}: the normalization or the grid construction is wrong."
        )
    if window_captured_fraction < MIN_WINDOW_CAPTURED_FRACTION:
        messages.append(
            f"window_captured_fraction = {window_captured_fraction:.4g} < "
            f"{MIN_WINDOW_CAPTURED_FRACTION:g}: the output window misses part of the "
            "envelope. Widen e_min/e_max."
        )
    if max_imaginary_ratio > MAX_IMAGINARY_RATIO:
        messages.append(
            f"max_imaginary_ratio = {max_imaginary_ratio:.3g} > {MAX_IMAGINARY_RATIO:g}: "
            "F(E) should be real; the symmetry rho(-tau) = conj(rho(tau)) is broken."
        )

    return tuple(messages)
