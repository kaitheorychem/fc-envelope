"""振電相互作用の流儀（g / huang_rhys）の正準化。"""

from __future__ import annotations

import numpy as np
import pytest
from conftest import compute_quietly

from fcenvelope import CouplingConvention, FCEnvelopeInput, VibrationalMode
from fcenvelope.models import to_huang_rhys

CONDITIONS = {
    "temperature": 300.0,
    "sigma": 150.0,
    "e_min": -4000.0,
    "e_max": 1000.0,
    "de": 5.0,
}


def _payload(convention: str, coupling: float) -> dict:
    return {
        "schema_version": 1,
        "frequency_unit": "cm^-1",
        "coupling_convention": convention,
        "modes": [{"frequency": 1200.0, "coupling": coupling}],
        "conditions": CONDITIONS,
    }


def test_registry_conversions():
    assert to_huang_rhys(0.5, CouplingConvention.G) == 0.25
    assert to_huang_rhys(0.25, CouplingConvention.HUANG_RHYS) == 0.25


def test_g_and_huang_rhys_agree():
    """g = 0.5 と huang_rhys = 0.25 は同一の結果を与える。"""
    from_g = FCEnvelopeInput.from_obj(_payload("g", 0.5))
    from_s = FCEnvelopeInput.from_obj(_payload("huang_rhys", 0.25))

    assert from_g.to_modes() == from_s.to_modes() == [
        VibrationalMode(frequency=1200.0, huang_rhys=0.25)
    ]

    result_g = compute_quietly(from_g.to_modes(), from_g.conditions)
    result_s = compute_quietly(from_s.to_modes(), from_s.conditions)

    np.testing.assert_array_equal(result_g.intensity, result_s.intensity)
    assert result_g.reorganization_energy == result_s.reorganization_energy


def test_default_convention_is_g():
    payload = _payload("g", 0.5)
    del payload["coupling_convention"]
    parsed = FCEnvelopeInput.from_obj(payload)
    assert parsed.coupling_convention is CouplingConvention.G
    assert parsed.to_modes()[0].huang_rhys == 0.25


@pytest.mark.parametrize("convention", ["Delta", "reorganization", ""])
def test_unknown_convention_is_rejected(convention):
    from fcenvelope.errors import InvalidInputError

    with pytest.raises(InvalidInputError):
        FCEnvelopeInput.from_obj(_payload(convention, 0.5))
