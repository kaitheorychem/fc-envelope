"""描画 API（合意文書 §9）。"""

from __future__ import annotations

import matplotlib.colors
import matplotlib.pyplot as plt
import numpy as np
import pytest
from conftest import compute_quietly, conditions, lines_quietly

from fcenvelope import (
    VibrationalMode,
    plot_envelope,
    plot_lines,
    plot_overlay,
)
from fcenvelope.errors import InvalidInputError

MODES = [VibrationalMode(frequency=1200.0, huang_rhys=0.5)]


@pytest.fixture
def result():
    return compute_quietly(
        MODES,
        **conditions(temperature=300.0, sigma=150.0, e_min=-8000.0, e_max=4000.0, de=5.0),
    )


def test_returns_a_figure_and_draws_the_spectrum(result):
    figure = plot_envelope(result)
    try:
        (line,) = figure.axes[0].lines[:1]
        np.testing.assert_array_equal(line.get_xdata(), result.energy)
        np.testing.assert_array_equal(line.get_ydata(), result.density)
    finally:
        plt.close(figure)


def test_accepts_an_existing_axes_for_overlays(result):
    figure, ax = plt.subplots()
    try:
        first = plot_envelope(result, ax=ax, label="300 K")
        second = plot_envelope(result, ax=ax, label="0 K")
        assert first is figure and second is figure
        assert len([line for line in ax.lines if line.get_label() in {"300 K", "0 K"}]) == 2
        assert ax.get_legend() is not None
    finally:
        plt.close(figure)


def test_title_is_applied(result):
    figure = plot_envelope(result, title="demo")
    try:
        assert figure.axes[0].get_title() == "demo"
    finally:
        plt.close(figure)


def test_saving_is_left_to_the_caller(result, tmp_path):
    figure = plot_envelope(result)
    try:
        assert not list(tmp_path.iterdir())
        target = tmp_path / "figure.png"
        figure.savefig(target)
        assert target.is_file()
    finally:
        plt.close(figure)


# --- 離散 FC 因子の棒スペクトル ---


@pytest.fixture
def lines_result():
    return lines_quietly(MODES, temperature=300.0, min_weight=1e-4)


def test_fc_lines_draws_one_stick_per_line(lines_result):
    figure = plot_lines(lines_result)
    try:
        (collection,) = figure.axes[0].collections
        segments = collection.get_segments()
        assert len(segments) == lines_result.diagnostics.n_lines
        # エネルギーが縮退した線もまとめずに 1 本ずつ描く。
        drawn = sorted((segment[0][0], segment[1][1]) for segment in segments)
        expected = sorted(
            (line.energy, line.weight) for line in lines_result.lines
        )
        np.testing.assert_allclose(drawn, expected)
        assert all(segment[0][1] == 0.0 for segment in segments)
    finally:
        plt.close(figure)


def test_fc_lines_accepts_an_existing_axes(lines_result):
    figure, ax = plt.subplots()
    try:
        assert plot_lines(lines_result, ax=ax, label="300 K") is figure
        assert ax.get_legend() is not None
    finally:
        plt.close(figure)


def test_fc_lines_title_is_applied(lines_result):
    figure = plot_lines(lines_result, title="sticks")
    try:
        assert figure.axes[0].get_title() == "sticks"
    finally:
        plt.close(figure)


# --- エンベロープと離散 FC 因子の重ね描き ---


OVERLAY_SIGMA = 80.0
OVERLAY_CONDITIONS = conditions(
    temperature=0.0, sigma=OVERLAY_SIGMA, e_min=-6000.0, e_max=2000.0, de=2.0
)


@pytest.fixture
def overlay_pair():
    """同じモード・同じ温度で求めたエンベロープと線リストの組。"""
    envelope = compute_quietly(MODES, **OVERLAY_CONDITIONS)
    lines = lines_quietly(MODES, temperature=0.0, min_weight=1e-6)
    return envelope, lines


def _envelope_line(ax, label="envelope"):
    (line,) = [item for item in ax.lines if item.get_label() == label]
    return line


def test_overlay_draws_both_on_a_single_axes(overlay_pair):
    envelope, lines = overlay_pair
    figure = plot_overlay(envelope, lines)
    try:
        # 縦軸を 2 本並べない。軸は 1 つだけ。
        (ax,) = figure.axes
        curve = _envelope_line(ax)
        np.testing.assert_array_equal(curve.get_xdata(), envelope.energy)
        np.testing.assert_array_equal(curve.get_ydata(), envelope.density)
        (collection,) = ax.collections
        assert len(collection.get_segments()) == lines.diagnostics.n_lines
    finally:
        plt.close(figure)


def test_overlay_scales_sticks_into_the_unit_of_the_envelope(overlay_pair):
    """棒の高さは線がエンベロープに立てる山の高さ I * G_sigma(0)。"""
    envelope, lines = overlay_pair
    figure = plot_overlay(envelope, lines)
    try:
        (collection,) = figure.axes[0].collections
        drawn = np.array(
            [(segment[0][0], segment[1][1]) for segment in collection.get_segments()]
        )
        scale = 1.0 / (OVERLAY_SIGMA * np.sqrt(2.0 * np.pi))
        expected = np.column_stack((lines.energies, lines.weights * scale))
        np.testing.assert_allclose(sorted(map(tuple, drawn)), sorted(map(tuple, expected)))
        # 底辺は 0 で、曲線と同じゼロ線から立ち上がる。
        assert all(segment[0][1] == 0.0 for segment in collection.get_segments())
    finally:
        plt.close(figure)


def test_overlay_stick_tips_touch_the_envelope_for_isolated_lines(overlay_pair):
    """1200 cm^-1 間隔は sigma = 80 に対して十分離れており、隣の線は効かない。"""
    envelope, lines = overlay_pair
    figure = plot_overlay(envelope, lines)
    try:
        (collection,) = figure.axes[0].collections
        for segment in collection.get_segments():
            energy, height = segment[0][0], segment[1][1]
            if not envelope.energy[0] <= energy <= envelope.energy[-1]:
                continue
            peak = np.interp(energy, envelope.energy, envelope.density)
            np.testing.assert_allclose(height, peak, rtol=1e-9)
    finally:
        plt.close(figure)


def test_overlay_frames_the_energy_window_of_the_envelope(overlay_pair):
    envelope, lines = overlay_pair
    figure = plot_overlay(envelope, lines)
    try:
        assert figure.axes[0].get_xlim() == (
            envelope.energy[0],
            envelope.energy[-1],
        )
    finally:
        plt.close(figure)


def test_overlay_labels_both_series_in_one_legend(overlay_pair):
    envelope, lines = overlay_pair
    figure = plot_overlay(envelope, lines, envelope_label="F(E)", lines_label="sticks")
    try:
        legend = figure.axes[0].get_legend()
        assert [text.get_text() for text in legend.get_texts()] == ["F(E)", "sticks"]
    finally:
        plt.close(figure)


def test_overlay_gives_the_two_series_different_colors(overlay_pair):
    envelope, lines = overlay_pair
    figure = plot_overlay(envelope, lines)
    try:
        ax = figure.axes[0]
        curve = matplotlib.colors.to_rgba(_envelope_line(ax).get_color())
        (collection,) = ax.collections
        sticks = tuple(collection.get_colors()[0])
        assert curve != sticks
    finally:
        plt.close(figure)


def test_overlay_title_is_applied(overlay_pair):
    envelope, lines = overlay_pair
    figure = plot_overlay(envelope, lines, title="overlay")
    try:
        assert figure.axes[0].get_title() == "overlay"
    finally:
        plt.close(figure)


def test_overlay_accepts_an_existing_axes(overlay_pair):
    envelope, lines = overlay_pair
    figure, ax = plt.subplots()
    try:
        assert plot_overlay(envelope, lines, ax=ax) is figure
        assert figure.axes == [ax]
    finally:
        plt.close(figure)


def test_overlay_warns_when_the_temperature_does_not_match(overlay_pair):
    envelope, _ = overlay_pair
    hot = lines_quietly(MODES, temperature=300.0, min_weight=1e-4)
    with pytest.warns(UserWarning, match="temperature mismatch"):
        plt.close(plot_overlay(envelope, hot))


def test_overlay_warns_when_the_modes_do_not_match(overlay_pair):
    envelope, _ = overlay_pair
    other = lines_quietly(
        [VibrationalMode(frequency=800.0, huang_rhys=0.3)], temperature=0.0
    )
    with pytest.warns(UserWarning, match="different modes"):
        plt.close(plot_overlay(envelope, other))


def test_overlay_magnifies_the_sticks_and_says_so_in_the_legend(overlay_pair):
    envelope, lines = overlay_pair
    plain = plot_overlay(envelope, lines)
    magnified = plot_overlay(envelope, lines, magnify=5.0)
    try:
        def tips(figure):
            (collection,) = figure.axes[0].collections
            return np.array([segment[1][1] for segment in collection.get_segments()])

        np.testing.assert_allclose(tips(magnified), tips(plain) * 5.0)
        (_, sticks) = magnified.axes[0].get_legend().get_texts()
        assert sticks.get_text() == r"FC lines ($\times$5)"
    finally:
        plt.close(plain)
        plt.close(magnified)


def test_overlay_leaves_the_label_alone_at_unit_magnification(overlay_pair):
    envelope, lines = overlay_pair
    figure = plot_overlay(envelope, lines)
    try:
        (_, sticks) = figure.axes[0].get_legend().get_texts()
        assert sticks.get_text() == "FC lines"
    finally:
        plt.close(figure)


@pytest.mark.parametrize("magnify", [0.0, -1.0])
def test_overlay_rejects_a_non_positive_magnification(overlay_pair, magnify):
    envelope, lines = overlay_pair
    with pytest.raises(InvalidInputError):
        plot_overlay(envelope, lines, magnify=magnify)
