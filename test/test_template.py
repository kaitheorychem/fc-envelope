"""入力ファイルの雛形の中身（ADR-0074）。

雛形は「この入力ファイルに何が書けるか」を見せるためのものなので、項目が増えたときに
黙って取り残されないよう、スキーマの側から数え上げて確かめる。そのまま動くことも
併せて見る。
"""

from __future__ import annotations

import re

import pytest

from fcenvelope import FCEnvelopeInput, compute_envelope
from fcenvelope.units import COUPLING_CONVENTIONS
from fcenvelope.inputs import (
    BroadeningSpec,
    EnergyGridSpec,
    GridPointsSpec,
    ModeSpec,
    SelectionSpec,
    template_text,
)

#: 雛形が触れているべき項目の出どころ。入力ファイルの型そのものから引く。
SPECS = (
    FCEnvelopeInput,
    ModeSpec,
    BroadeningSpec,
    EnergyGridSpec,
    GridPointsSpec,
    SelectionSpec,
)

FIELDS = [
    (spec.__name__, field) for spec in SPECS for field in spec.model_fields
]


def test_the_template_is_a_working_input_file(tmp_path):
    path = tmp_path / "input.toml"
    path.write_text(template_text(), encoding="utf-8")

    parsed = FCEnvelopeInput.from_path(path)
    result = compute_envelope(
        parsed.to_system(),
        temperature=parsed.to_temperature(),
        broadening=parsed.to_broadening(),
        grid=parsed.to_grid(),
    )

    assert result.energy.size > 0


@pytest.mark.parametrize(("spec", "field"), FIELDS, ids=lambda part: part)
def test_the_template_mentions_every_field(spec, field):
    """項目はすべて雛形に出てくる。書けない組み合わせのものはコメントとして出てくる。

    `coupling_unit` は無次元の流儀では書けず、`grid.points` の `n` と `de` は排他なので、
    雛形に生きた行として置けるのは片方だけである。行頭のコメントも数に入れる。
    """
    del spec  # 失敗したときにどの型の項目かが読めるようにしてあるだけ。
    pattern = rf"^(?:#\s*)?(?:\[+[\w.]*\b{re.escape(field)}\]+|{re.escape(field)}\s*=)"

    assert re.search(pattern, template_text(), re.MULTILINE), field


def test_every_field_line_carries_a_comment():
    """値を書く行には、それが何の数かの短いコメントが付く（ADR-0074）。

    2 つ目以降の `[[modes]]` は 1 つ目と同じ項目の繰り返しなので、そこは見ない。
    """
    lines = template_text().splitlines()
    first_repeat = lines.index("[[modes]]", lines.index("[[modes]]") + 1)

    for line in lines[:first_repeat]:
        if re.match(r"^\w+\s*=", line):
            assert "#" in line, line


@pytest.mark.parametrize("name", sorted(COUPLING_CONVENTIONS))
def test_the_template_names_every_coupling_convention(name):
    """流儀を足したら雛形のコメントにも出てくること。"""
    assert name in template_text(), name
