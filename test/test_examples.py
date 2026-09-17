"""文書に載っている入力例が実際に読めること（ADR-0056）。

例は `docs/readme/usage.md` の説明が動くことを示すものなので、説明と食い違ったまま
残らないようにここで見る。ディレクトリの中身を数え上げるため、例を足せばその例も
自動的に検証される。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fcenvelope import FCEnvelopeInput, compute_envelope, units

EXAMPLES = sorted((Path(__file__).resolve().parents[1] / "docs/readme/examples").glob("*.json"))


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


def test_sigma_in_ev_matches_the_documented_cm_inverse_width():
    """usage.md の例が使う 150 cm^-1 と同じ幅を eV で書いたものであること。"""
    parsed = FCEnvelopeInput.from_path(
        Path(__file__).resolve().parents[1] / "docs/readme/examples/sigma-in-ev.json"
    )

    assert parsed.broadening.unit == "eV"
    assert parsed.grid.unit == units.CANONICAL_ENERGY_UNIT
    assert parsed.to_broadening().sigma == pytest.approx(150.0, rel=1e-3)
