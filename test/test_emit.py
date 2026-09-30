"""作図スクリプトの生成（ADR-0057〜0062）。

生成物は**利用者の手元で単独で走るプログラム**なので、ここでは文字列を読むだけで
なく実際に subprocess で走らせて確かめる。図の設定がスクリプトの中にあることは、
`fcenvelope` を import していないことで見る。
"""

from __future__ import annotations

import base64
import json
import os
import re
import struct
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import compute_quietly, lines_quietly, run_script

from fcenvelope import Broadening, EnergyGrid, save_envelope, save_lines
from fcenvelope.io import SCHEMA_VERSION
from fcenvelope.emit import (
    MODES_TEMPLATE,
    TEMPLATES,
    image_path_for,
    script_path_for,
    write_modes_script,
    write_overlay_script,
    write_script,
)

KITTY_CHUNK = re.compile(rb"\033_G([^;]*);([^\033]*)\033\\")


def run_script_on_a_terminal(
    script: Path,
    *,
    xpixel: int,
    ypixel: int = 900,
    columns: int = 160,
    rows: int = 40,
    tmux: bool = False,
) -> bytes:
    """疑似端末に繋いで走らせ、端末に流れたバイト列を返す。`tmux` なら tmux の中のふり。"""
    pty = pytest.importorskip("pty")
    import fcntl
    import termios

    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, xpixel, ypixel))
    process = subprocess.Popen(
        [sys.executable, str(script)],
        stdout=slave,
        stderr=subprocess.PIPE,
        env={
            **{key: value for key, value in os.environ.items() if key != "TMUX"},
            "MPLBACKEND": "Agg",
            **({"TMUX": "/tmp/tmux-0/default,1,0"} if tmux else {}),
        },
    )
    os.close(slave)

    written = bytearray()
    try:
        while chunk := os.read(master, 65536):
            written += chunk
    except OSError:  # 相手が閉じたら読み終わり
        pass
    process.wait()
    os.close(master)
    assert process.returncode == 0, process.stderr.read().decode()
    return bytes(written)


def reassemble(stream: bytes) -> bytes:
    """kitty graphics protocol のチャンクを繋いで画像に戻す。"""
    chunks = KITTY_CHUNK.findall(stream)
    assert chunks, "端末に画像が流れていない"
    assert chunks[0][0].startswith(b"a=T,f=100,q=2,"), chunks[0][0]
    assert all(control.endswith(b"m=1") for control, _ in chunks[:-1])
    assert chunks[-1][0].endswith(b"m=0")
    assert max(len(payload) for _, payload in chunks) <= 4096
    return base64.standard_b64decode(b"".join(payload for _, payload in chunks))


def png_size(png: bytes) -> tuple[int, int]:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", png[16:24])  # IHDR の幅と高さ


@pytest.fixture
def envelope(multi_mode):
    return compute_quietly(
        multi_mode,
        temperature=300.0,
        broadening=Broadening(sigma=150.0),
        grid=EnergyGrid.from_spacing(e_min=-6000.0, e_max=2000.0, de=5.0),
    )


@pytest.fixture
def lines(multi_mode):
    return lines_quietly(multi_mode, temperature=300.0, min_weight=1e-3)


@pytest.fixture
def envelope_script(tmp_path, envelope):
    data = tmp_path / "result.json"
    save_envelope(envelope, data)
    script = script_path_for(data)
    assert write_script(envelope, data, script)
    return script


@pytest.fixture
def lines_script(tmp_path, lines):
    data = tmp_path / "lines.json"
    save_lines(lines, data)
    script = script_path_for(data)
    assert write_script(lines, data, script)
    return script


@pytest.fixture
def overlay_script(tmp_path, envelope, lines):
    envelope_data, lines_data = tmp_path / "result.json", tmp_path / "lines.json"
    save_envelope(envelope, envelope_data)
    save_lines(lines, lines_data)
    script = tmp_path / "overlay_plot.py"
    assert write_overlay_script(envelope, envelope_data, lines, lines_data, script)
    return script


@pytest.fixture
def modes_script(tmp_path, lines):
    data = tmp_path / "lines.json"
    save_lines(lines, data)
    script = tmp_path / "modes_plot.py"
    assert write_modes_script(lines, data, script)
    return script


# --- 名前の付け方 ---


def test_the_script_is_named_after_the_data_it_plots(tmp_path):
    assert script_path_for(tmp_path / "result.json") == tmp_path / "result_plot.py"


def test_the_image_is_named_after_the_program(tmp_path):
    """画像は単独で持ち出されるので、どのプログラムの図かを名前に残す（ADR-0061）。"""
    assert image_path_for(tmp_path / "result_plot.py") == tmp_path / "fcenvelope-result.png"
    assert image_path_for(tmp_path / "myfig.py") == tmp_path / "fcenvelope-myfig.png"


# --- 生成されたスクリプトが単独で走る ---


@pytest.mark.parametrize(
    "name", ["envelope_script", "lines_script", "overlay_script", "modes_script"]
)
def test_the_script_runs_on_its_own_and_writes_the_image(name, request):
    script = request.getfixturevalue(name)
    image = image_path_for(script)

    finished = run_script(script)

    assert finished.returncode == 0, finished.stderr.decode()
    assert image.is_file() and image.stat().st_size > 0
    assert str(image) in finished.stdout.decode()


#: 生成されたスクリプトが import してよいもの。標準ライブラリと matplotlib だけで、
#: `fcenvelope` は入らない（ADR-0058）。増えたらここに足すかどうかを考える。
ALLOWED_IMPORTS = {
    "__future__", "base64", "fcntl", "io", "json", "math",
    "matplotlib", "os", "pathlib", "struct", "sys", "termios",
}


def imported_modules(script: Path) -> set[str]:
    """スクリプトが import している最上位のモジュール名。"""
    import ast

    found = set()
    for node in ast.walk(ast.parse(script.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            found.add(node.module.split(".")[0])
    return found


@pytest.mark.parametrize(
    "name", ["envelope_script", "lines_script", "overlay_script", "modes_script"]
)
def test_the_script_does_not_depend_on_fcenvelope(name, request):
    """図の設定がスクリプトの中で完結していることの裏返し（ADR-0058）。"""
    imported = imported_modules(request.getfixturevalue(name))
    assert "fcenvelope" not in imported
    assert imported <= ALLOWED_IMPORTS, imported - ALLOWED_IMPORTS


@pytest.fixture
def colder(tmp_path, multi_mode):
    """同じ系を温度だけ変えて計算した、2 つめの結果ファイル。"""
    data = tmp_path / "colder.json"
    save_envelope(
        compute_quietly(
            multi_mode,
            temperature=0.0,
            broadening=Broadening(sigma=150.0),
            grid=EnergyGrid.from_spacing(e_min=-6000.0, e_max=2000.0, de=5.0),
        ),
        data,
    )
    return data


def test_the_script_can_be_pointed_at_another_data_file(envelope_script, colder):
    """条件を振った結果に同じ設定を当てられる。"""
    finished = run_script(envelope_script, str(colder))

    assert finished.returncode == 0, finished.stderr.decode()
    assert image_path_for(script_path_for(colder)).is_file()


def test_the_image_follows_the_data_the_script_was_pointed_at(envelope_script, colder):
    """引数でほかの結果を描いたときに、既定のデータの図を潰さない（ADR-0067）。"""
    run_script(envelope_script)
    default_image = image_path_for(envelope_script)
    stamp = default_image.stat().st_mtime_ns

    finished = run_script(envelope_script, str(colder))

    assert finished.returncode == 0, finished.stderr.decode()
    assert (colder.parent / "fcenvelope-colder.png").is_file()
    assert default_image.stat().st_mtime_ns == stamp


def test_the_image_of_an_argument_carries_that_data_in_its_metadata(envelope_script, colder):
    """覚え書きの出どころも、生成時のデータではなく実際に読んだデータである。"""
    from PIL import PngImagePlugin

    run_script(envelope_script, str(colder))

    with PngImagePlugin.PngImageFile(colder.parent / "fcenvelope-colder.png") as image:
        info = image.info
    assert "colder.json" in info["Source"]
    assert "T = 0 K" in info["Description"]


def test_a_relative_argument_is_read_from_the_current_directory(tmp_path, envelope_script, colder):
    """コマンドラインの引数はシェルの規則どおりカレントディレクトリ基準（ADR-0067）。"""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    finished = subprocess.run(
        [sys.executable, str(envelope_script), "../colder.json"],
        capture_output=True,
        cwd=elsewhere,
        env={**os.environ, "MPLBACKEND": "Agg"},
        check=False,
    )

    assert finished.returncode == 0, finished.stderr.decode()
    assert (colder.parent / "fcenvelope-colder.png").is_file()


def test_a_name_written_in_the_script_is_read_from_beside_the_script(
    tmp_path, envelope_script, colder
):
    """スクリプトの中に書いた名前はスクリプトの隣が基準（ADR-0067）。

    2 本目を重ねる書き方が、どのディレクトリから起動しても動くことを見る。
    """
    text = envelope_script.read_text(encoding="utf-8")
    envelope_script.write_text(
        text.replace(
            '    # draw(ax, load("result_100K.json", KIND), label="100 K", color="C3")',
            '    draw(ax, load("colder.json", KIND), label="0 K", color="C3")',
        ),
        encoding="utf-8",
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    finished = subprocess.run(
        [sys.executable, str(envelope_script)],
        capture_output=True,
        cwd=elsewhere,
        env={**os.environ, "MPLBACKEND": "Agg"},
        check=False,
    )

    assert finished.returncode == 0, finished.stderr.decode()
    assert image_path_for(envelope_script).is_file()


def test_the_overlay_image_follows_the_envelope_it_was_pointed_at(
    overlay_script, colder, tmp_path
):
    """重ねた図だと名前に残し、同じ結果を単独で描いた図と分ける（ADR-0067）。"""
    finished = run_script(overlay_script, str(colder), str(tmp_path / "lines.json"))

    assert finished.returncode == 0, finished.stderr.decode()
    assert (colder.parent / "fcenvelope-colder-overlay.png").is_file()


def test_the_script_stops_on_a_result_of_the_wrong_kind(tmp_path, envelope_script, lines):
    wrong = tmp_path / "lines.json"
    save_lines(lines, wrong)

    finished = run_script(envelope_script, str(wrong))

    assert finished.returncode != 0
    assert "expected fcenvelope.envelope" in finished.stderr.decode()


def test_the_script_stops_on_a_result_of_another_schema(tmp_path, envelope_script):
    data = tmp_path / "result.json"
    payload = json.loads(data.read_text(encoding="utf-8"))
    payload["schema_version"] = 99
    data.write_text(json.dumps(payload), encoding="utf-8")

    finished = run_script(envelope_script)

    assert finished.returncode != 0
    assert f"schema {SCHEMA_VERSION}" in finished.stderr.decode()


def test_the_overlay_script_reports_lines_outside_the_energy_window(
    tmp_path, multi_mode, lines
):
    narrow = compute_quietly(
        multi_mode,
        temperature=300.0,
        broadening=Broadening(sigma=150.0),
        grid=EnergyGrid.from_spacing(e_min=-300.0, e_max=300.0, de=5.0),
    )
    envelope_data, lines_data = tmp_path / "narrow.json", tmp_path / "lines.json"
    save_envelope(narrow, envelope_data)
    save_lines(lines, lines_data)
    script = tmp_path / "overlay_plot.py"
    write_overlay_script(narrow, envelope_data, lines, lines_data, script)

    finished = run_script(script)

    assert finished.returncode == 0, finished.stderr.decode()
    assert "outside the E window" in finished.stderr.decode()


# --- 2 つの出力先 ---


@pytest.mark.parametrize(
    "name", ["envelope_script", "lines_script", "overlay_script", "modes_script"]
)
def test_nothing_is_written_to_a_stdout_that_is_not_a_terminal(name, request):
    finished = run_script(request.getfixturevalue(name))
    assert b"\033_G" not in finished.stdout


def test_the_figure_goes_to_a_terminal_as_a_kitty_graphics_stream(envelope_script):
    stream = run_script_on_a_terminal(envelope_script, xpixel=1600)
    png = reassemble(stream)
    # 窓 1600x900 の半分に収まる。この窓では高さが先に効く: 900 * 0.5 / 4.2 dpi。
    assert png_size(png) == (round(7.0 * 450 / 4.2), round(450))
    assert b"\033Ptmux;" not in stream


@pytest.mark.parametrize("xpixel, ypixel", [(800, 900), (2400, 900), (2400, 2400)])
def test_the_figure_fits_in_half_of_the_terminal(envelope_script, xpixel, ypixel):
    png = reassemble(run_script_on_a_terminal(envelope_script, xpixel=xpixel, ypixel=ypixel))
    width, height = png_size(png)
    assert width <= xpixel * 0.5 + 1 and height <= ypixel * 0.5 + 1
    # 狭い方の向きでちょうど半分になる。
    assert max(width / (xpixel * 0.5), height / (ypixel * 0.5)) == pytest.approx(1.0, abs=0.01)


def test_a_terminal_that_reports_no_pixels_falls_back_to_a_fixed_resolution(
    envelope_script,
):
    stream = run_script_on_a_terminal(envelope_script, xpixel=0, ypixel=0)
    png = reassemble(stream)
    assert png_size(png)[0] == round(7.0 * 110)  # FIGSIZE[0] * SHOW_DPI
    # 大きさは端末に任せ、窓の行数の半分に収めさせる。
    assert b"r=20," in KITTY_CHUNK.findall(stream)[0][0]


def test_in_tmux_the_stream_is_passed_through_and_the_cursor_moved(envelope_script):
    stream = run_script_on_a_terminal(envelope_script, xpixel=1600, tmux=True)
    assert b"\033Ptmux;\033\033_G" in stream, "tmux の中なのに包まれていない"
    assert b"\033_G" not in stream.replace(b"\033\033_G", b"")  # 素の列は流さない
    unwrapped = stream.replace(b"\033Ptmux;", b"").replace(b"\033\033", b"\033")
    png = reassemble(unwrapped)
    control = KITTY_CHUNK.findall(unwrapped)[0][0]
    assert b"C=1," in control
    # 画像の高さ 450 px は 900 px / 40 行で 20 行ぶん。tmux のカーソルをその下へ送る。
    assert png_size(png)[1] == 450
    assert stream.endswith(b"\033\\" + b"\r\n" * 20)


def test_the_image_file_keeps_its_own_resolution_on_a_terminal(envelope_script):
    """端末に合わせるのは端末に出す図だけで、ファイルの DPI は動かない。"""
    run_script_on_a_terminal(envelope_script, xpixel=2400)
    assert png_size(image_path_for(envelope_script).read_bytes())[0] == round(7.0 * 150)


def test_the_image_carries_the_provenance_in_its_metadata(envelope_script):
    from PIL import PngImagePlugin

    run_script(envelope_script)
    with PngImagePlugin.PngImageFile(image_path_for(envelope_script)) as image:
        info = image.info
    assert info["Software"].startswith("fcenvelope ")
    assert "result.json" in info["Source"]
    assert "T = 300 K" in info["Description"]


# --- 生成の規則 ---


def test_an_existing_script_is_kept(tmp_path, envelope, envelope_script):
    envelope_script.write_text("# 手で直した\n", encoding="utf-8")

    assert not write_script(envelope, tmp_path / "result.json", envelope_script)
    assert envelope_script.read_text(encoding="utf-8") == "# 手で直した\n"


def test_force_overwrites_an_existing_script(tmp_path, envelope, envelope_script):
    envelope_script.write_text("# 手で直した\n", encoding="utf-8")

    assert write_script(envelope, tmp_path / "result.json", envelope_script, force=True)
    assert "def draw(" in envelope_script.read_text(encoding="utf-8")


def test_only_the_generated_header_differs_from_the_template(envelope_script):
    """雛形のうち生成が触るのはマーカーの間だけである（ADR-0059）。"""
    from importlib import resources

    template = (
        resources.files("fcenvelope")
        .joinpath("templates", "envelope.py")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    written = envelope_script.read_text(encoding="utf-8").splitlines()

    def below_the_header(lines: list[str]) -> list[str]:
        end = next(i for i, line in enumerate(lines) if line.startswith("# --- end generated"))
        return lines[end:]

    assert below_the_header(written) == below_the_header(template)


def test_the_script_reaches_data_in_another_directory(tmp_path, envelope):
    data = tmp_path / "data" / "result.json"
    data.parent.mkdir()
    save_envelope(envelope, data)
    script = tmp_path / "figures" / "result_plot.py"

    assert write_script(envelope, data, script)
    finished = run_script(script)

    assert finished.returncode == 0, finished.stderr.decode()
    assert (tmp_path / "figures" / "fcenvelope-result.png").is_file()


def test_every_template_shares_one_copy_of_the_common_helpers():
    """すべての雛形で共通の部分が食い違わないようにする。"""
    from importlib import resources

    def helpers(name: str) -> str:
        text = (
            resources.files("fcenvelope")
            .joinpath("templates", f"{name}.py")
            .read_text(encoding="utf-8")
        )
        start = text.index("def beside(")
        return text[start : text.index("def image_for(")]

    shared = {helpers(name) for name in {*TEMPLATES.values(), "overlay", MODES_TEMPLATE}}
    assert len(shared) == 1


# --- モードごとの結合（ADR-0083） ---


def draw_with(script: Path, data: Path, **settings):
    """生成されたスクリプトを import し、設定を差し替えて `draw` だけを走らせる。"""
    import importlib.util

    import matplotlib.pyplot as plt

    spec = importlib.util.spec_from_file_location("generated", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name, value in settings.items():
        setattr(module, name, value)
    figure, ax = plt.subplots()
    try:
        module.draw(ax, module.load(data, module.KIND))
        (collection,) = ax.collections
        sticks = sorted((s[0][0], s[1][1]) for s in collection.get_segments())
        return sticks, ax.get_xlabel(), ax.get_ylabel()
    finally:
        plt.close(figure)


def test_the_modes_script_draws_g_at_each_frequency(modes_script, multi_mode):
    sticks, xlabel, ylabel = draw_with(modes_script, modes_script.parent / "lines.json")

    expected = sorted((m.frequency, m.huang_rhys**0.5) for m in multi_mode.modes)
    assert sticks == pytest.approx(expected)
    assert ylabel == "$g$" and xlabel.startswith(r"$\omega$") and "cm" in xlabel


def test_the_modes_script_can_draw_s_in_another_unit(modes_script, multi_mode):
    sticks, xlabel, ylabel = draw_with(
        modes_script,
        modes_script.parent / "lines.json",
        Y="S",
        X_UNIT="eV",
        X_SCALE=1.0 / 8065.543937,
    )

    expected = sorted((m.frequency / 8065.543937, m.huang_rhys) for m in multi_mode.modes)
    assert sticks == pytest.approx(expected)
    assert ylabel == "$S$" and "eV" in xlabel


def test_the_modes_script_reads_an_envelope_result_too(tmp_path, envelope, multi_mode):
    data = tmp_path / "result.json"
    save_envelope(envelope, data)
    script = tmp_path / "modes_plot.py"
    assert write_modes_script(envelope, data, script)

    finished = run_script(script)
    assert finished.returncode == 0, finished.stderr.decode()
    assert image_path_for(script).is_file()

    sticks, _, _ = draw_with(script, data)
    assert len(sticks) == len(multi_mode.modes)


def test_an_existing_modes_script_is_kept(tmp_path, lines, modes_script):
    modes_script.write_text("# 手で直した\n", encoding="utf-8")

    assert not write_modes_script(lines, tmp_path / "lines.json", modes_script)
    assert modes_script.read_text(encoding="utf-8") == "# 手で直した\n"
