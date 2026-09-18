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
from conftest import compute_quietly, lines_quietly

from fcenvelope import Broadening, EnergyGrid, save_envelope, save_lines
from fcenvelope.emit import (
    TEMPLATES,
    image_path_for,
    script_path_for,
    write_overlay_script,
    write_script,
)

KITTY_CHUNK = re.compile(rb"\033_G([^;]*);([^\033]*)\033\\")


def run_script(script: Path, *arguments: str) -> subprocess.CompletedProcess:
    """生成されたスクリプトを、標準出力が端末でない状態で走らせる。"""
    return subprocess.run(
        [sys.executable, str(script), *arguments],
        capture_output=True,
        env={**os.environ, "MPLBACKEND": "Agg"},
        check=False,
    )


def run_script_on_a_terminal(
    script: Path, *, xpixel: int, ypixel: int = 900, columns: int = 160, rows: int = 40
) -> bytes:
    """疑似端末に繋いで走らせ、端末に流れたバイト列を返す。"""
    pty = pytest.importorskip("pty")
    import fcntl
    import termios

    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, xpixel, ypixel))
    process = subprocess.Popen(
        [sys.executable, str(script)],
        stdout=slave,
        stderr=subprocess.PIPE,
        env={**os.environ, "MPLBACKEND": "Agg"},
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
        grid=EnergyGrid(e_min=-6000.0, e_max=2000.0, de=5.0),
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


# --- 名前の付け方 ---


def test_the_script_is_named_after_the_data_it_plots(tmp_path):
    assert script_path_for(tmp_path / "result.json") == tmp_path / "result_plot.py"


def test_the_image_is_named_after_the_program(tmp_path):
    """画像は単独で持ち出されるので、どのプログラムの図かを名前に残す（ADR-0061）。"""
    assert image_path_for(tmp_path / "result_plot.py") == tmp_path / "fcenvelope-result.png"
    assert image_path_for(tmp_path / "myfig.py") == tmp_path / "fcenvelope-myfig.png"


# --- 生成されたスクリプトが単独で走る ---


@pytest.mark.parametrize("name", ["envelope_script", "lines_script", "overlay_script"])
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
    "matplotlib", "pathlib", "struct", "sys", "termios",
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


@pytest.mark.parametrize("name", ["envelope_script", "lines_script", "overlay_script"])
def test_the_script_does_not_depend_on_fcenvelope(name, request):
    """図の設定がスクリプトの中で完結していることの裏返し（ADR-0058）。"""
    imported = imported_modules(request.getfixturevalue(name))
    assert "fcenvelope" not in imported
    assert imported <= ALLOWED_IMPORTS, imported - ALLOWED_IMPORTS


def test_the_script_can_be_pointed_at_another_data_file(tmp_path, envelope_script, multi_mode):
    """条件を振った結果に同じ設定を当てられる。"""
    other = tmp_path / "colder.json"
    save_envelope(
        compute_quietly(
            multi_mode,
            temperature=0.0,
            broadening=Broadening(sigma=150.0),
            grid=EnergyGrid(e_min=-6000.0, e_max=2000.0, de=5.0),
        ),
        other,
    )

    finished = run_script(envelope_script, str(other))

    assert finished.returncode == 0, finished.stderr.decode()
    assert image_path_for(envelope_script).is_file()


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
    assert "schema 2" in finished.stderr.decode()


def test_the_overlay_script_reports_lines_outside_the_energy_window(
    tmp_path, multi_mode, lines
):
    narrow = compute_quietly(
        multi_mode,
        temperature=300.0,
        broadening=Broadening(sigma=150.0),
        grid=EnergyGrid(e_min=-300.0, e_max=300.0, de=5.0),
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


@pytest.mark.parametrize("name", ["envelope_script", "lines_script", "overlay_script"])
def test_nothing_is_written_to_a_stdout_that_is_not_a_terminal(name, request):
    finished = run_script(request.getfixturevalue(name))
    assert b"\033_G" not in finished.stdout


def test_the_figure_goes_to_a_terminal_as_a_kitty_graphics_stream(envelope_script):
    png = reassemble(run_script_on_a_terminal(envelope_script, xpixel=1600))
    assert png_size(png)[0] == round(1600 * 0.9)


def test_the_figure_follows_the_width_of_the_terminal(envelope_script):
    narrow = reassemble(run_script_on_a_terminal(envelope_script, xpixel=800))
    wide = reassemble(run_script_on_a_terminal(envelope_script, xpixel=2400))
    assert png_size(narrow)[0] == round(800 * 0.9)
    assert png_size(wide)[0] == round(2400 * 0.9)


def test_a_terminal_that_reports_no_pixels_falls_back_to_a_fixed_resolution(
    envelope_script,
):
    png = reassemble(run_script_on_a_terminal(envelope_script, xpixel=0, ypixel=0))
    assert png_size(png)[0] == round(7.0 * 110)  # FIGSIZE[0] * SHOW_DPI


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
    """3 つの雛形で共通の部分が食い違わないようにする。"""
    from importlib import resources

    def helpers(name: str) -> str:
        text = (
            resources.files("fcenvelope")
            .joinpath("templates", f"{name}.py")
            .read_text(encoding="utf-8")
        )
        start = text.index("def load(")
        return text[start : text.index("def ", text.index("def show(") + 1)]

    shared = {helpers(name) for name in {*TEMPLATES.values(), "overlay"}}
    assert len(shared) == 1
