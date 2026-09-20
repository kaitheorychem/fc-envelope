"""文書に載っている入力例が実際に読めること（ADR-0056）。

例は `docs/readme/usage.md` の説明が動くことを示すものなので、説明と食い違ったまま
残らないようにここで見る。ディレクトリの中身を数え上げるため、例を足せばその例も
自動的に検証される。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fcenvelope import FCEnvelopeInput, compute_envelope, units
from fcenvelope.inputs import INPUT_FORMATS

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "docs/readme/examples"

#: 例の書式は入力ファイルが受け付けるものと同じ（ADR-0069）。片方の書式の例だけが
#: 検証される状態にならないよう、拡張子は `INPUT_FORMATS` から引く。
EXAMPLES = sorted(
    path
    for suffix in INPUT_FORMATS
    for path in EXAMPLES_DIR.glob(f"*{suffix}")
)


def test_there_is_at_least_one_example():
    assert EXAMPLES


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_an_example_parses_and_computes(path):
    parsed = FCEnvelopeInput.from_path(path)
    result = compute_envelope(
        parsed.to_system(),
        temperature=parsed.to_temperature(),
        broadening=parsed.to_broadening(),
        grid=parsed.to_grid(),
    )
    assert result.energy.size > 0


def test_there_is_an_example_in_every_format():
    """どの書式にも例が 1 つはあること。文書が TOML を基本に書いているので（ADR-0069）、
    JSON の例だけが残って TOML が検証されない状態を防ぐ。"""
    for suffix in INPUT_FORMATS:
        assert any(path.suffix == suffix for path in EXAMPLES), suffix


@pytest.mark.parametrize("suffix", sorted(INPUT_FORMATS), ids=lambda s: s.lstrip("."))
def test_sigma_in_ev_matches_the_documented_cm_inverse_width(suffix):
    """usage.md の例が使う 150 cm^-1 と同じ幅を eV で書いたものであること。"""
    parsed = FCEnvelopeInput.from_path(EXAMPLES_DIR / f"sigma-in-ev{suffix}")

    assert parsed.broadening.unit == "eV"
    assert parsed.grid.unit == units.CANONICAL_ENERGY_UNIT
    assert parsed.to_broadening().sigma == pytest.approx(150.0, rel=1e-3)


def test_the_two_sigma_in_ev_examples_say_the_same_thing():
    """同じ入力を TOML と JSON で書いたら、実効設定まで一致すること（ADR-0069）。

    書式が違っても読んだ後は同じで、以降の扱いは変わらない——という約束を、文書が
    並べて見せている 2 つの例そのもので見る。
    """
    from_toml = FCEnvelopeInput.from_path(EXAMPLES_DIR / "sigma-in-ev.toml")
    from_json = FCEnvelopeInput.from_path(EXAMPLES_DIR / "sigma-in-ev.json")

    assert from_toml.to_json() == from_json.to_json()


def test_units_on_values_says_the_same_thing_as_the_block_unit_example():
    """値に単位を添えた例が、同じ物理系を単位フィールドで書いた例と一致すること。

    `units-on-values.toml` は組の書き方（ADR-0072）を見せるためのもので、丸めた
    桁数のぶんだけずれる。同じ系を指していることが分かる精度で見る。
    """
    parsed = FCEnvelopeInput.from_path(EXAMPLES_DIR / "units-on-values.toml")

    assert parsed.grid.unit == "eV"  # グリッドはブロックの単位でまとめて指定
    assert parsed.broadening.unit == units.CANONICAL_ENERGY_UNIT  # σ は値の側で eV
    assert parsed.to_broadening().sigma == pytest.approx(150.0, rel=1e-3)
    frequencies = [mode.frequency for mode in parsed.to_system().modes]
    assert frequencies == pytest.approx([1200.0, 450.0], rel=1e-3)
    grid = parsed.to_grid()
    assert (grid.e_min, grid.e_max, grid.de) == pytest.approx(
        (-4500.0, 1000.0, 4.0), rel=1e-3
    )
