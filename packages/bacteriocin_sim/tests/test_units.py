"""Unit handling and condition resolution.

Cell density is a first-class experimental variable in this model, so a silent
unit error -- OD600 read as CFU/mL is nine orders of magnitude -- would corrupt
every prediction that depends on it. These tests pin the conversions down.
"""

from __future__ import annotations

import pytest

from bacteriocin_sim import run_experiment
from bacteriocin_sim.model import peptide as pep
from bacteriocin_sim.model.environment import (
    free_concentration_um,
    to_cfu_per_ml,
    to_micromolar,
)
from bacteriocin_sim.schemas import Quantity
from bacteriocin_sim.selftest import NISIN_A, spec


def test_od600_is_converted_with_the_organism_factor() -> None:
    warnings: list[str] = []
    value = to_cfu_per_ml(
        Quantity(value=0.5, unit="od600"), od600_to_cfu=1.0e9, warnings=warnings, label="d"
    )
    assert value == pytest.approx(5.0e8)
    assert not warnings


def test_log10_density_is_converted() -> None:
    warnings: list[str] = []
    value = to_cfu_per_ml(
        Quantity(value=6.0, unit="log10_cfu_per_ml"),
        od600_to_cfu=1.0e9,
        warnings=warnings,
        label="d",
    )
    assert value == pytest.approx(1.0e6)


def test_bare_density_number_warns_about_the_assumed_unit() -> None:
    warnings: list[str] = []
    value = to_cfu_per_ml(1.0e6, od600_to_cfu=1.0e9, warnings=warnings, label="density")
    assert value == 1.0e6
    assert any("without a unit" in w for w in warnings)


def test_mass_concentration_needs_a_molecular_weight() -> None:
    warnings: list[str] = []
    value = to_micromolar(
        Quantity(value=3.354, unit="ug_per_ml"), molecular_weight_da=3354.0, warnings=warnings
    )
    assert value == pytest.approx(1.0, rel=1e-3)
    assert not warnings


def test_mass_concentration_without_a_weight_warns_instead_of_guessing() -> None:
    warnings: list[str] = []
    to_micromolar(
        Quantity(value=10.0, unit="ug_per_ml"), molecular_weight_da=None, warnings=warnings
    )
    assert any("no molecular weight" in w for w in warnings)


def test_activity_units_are_refused_rather_than_misconverted() -> None:
    warnings: list[str] = []
    value = to_micromolar(
        Quantity(value=1000.0, unit="iu_per_ml"), molecular_weight_da=3354.0, warnings=warnings
    )
    assert value is None
    assert any("cannot be converted to molarity" in w for w in warnings)


def test_od600_and_equivalent_cfu_give_the_same_prediction() -> None:
    by_cfu = run_experiment(
        spec(conditions={"target_cell_density": {"value": 1.0e9, "unit": "cfu_per_ml"}})
    )
    by_od = run_experiment(
        spec(conditions={"target_cell_density": {"value": 1.0, "unit": "od600"}})
    )
    assert by_cfu.measurement.predicted_inhibition_fraction == pytest.approx(
        by_od.measurement.predicted_inhibition_fraction, abs=1e-6
    )


def test_minutes_and_hours_agree() -> None:
    by_hours = run_experiment(spec(conditions={"incubation_time": 2.0}))
    by_minutes = run_experiment(
        spec(conditions={"incubation_time": 120.0, "incubation_time_unit": "min"})
    )
    assert by_hours.measurement.predicted_inhibition_fraction == pytest.approx(
        by_minutes.measurement.predicted_inhibition_fraction, abs=1e-6
    )


def test_langmuir_mass_balance_is_conservative() -> None:
    """Free peptide can never exceed the total, and binding must be monotone."""
    total = 2.0
    previous = total + 1.0
    for sites in (0.0, 0.1, 1.0, 10.0, 100.0):
        free = free_concentration_um(total, sites, kd_um=1.0)
        assert 0.0 <= free <= total
        assert free <= previous + 1e-12
        previous = free


def test_charge_decreases_with_rising_ph() -> None:
    charges = [pep.net_charge_at_ph(NISIN_A, ph) for ph in (3.0, 5.0, 7.0, 9.0, 11.0)]
    assert all(b < a for a, b in zip(charges, charges[1:]))


def test_isoelectric_point_is_the_charge_zero_crossing() -> None:
    pi = pep.isoelectric_point(NISIN_A)
    assert abs(pep.net_charge_at_ph(NISIN_A, pi)) < 0.01


def test_pediocin_box_is_detected() -> None:
    from bacteriocin_sim.schemas import BacteriocinClass
    from bacteriocin_sim.selftest import PEDIOCIN_PA1

    inferred, confidence, _ = pep.infer_class(PEDIOCIN_PA1)
    assert inferred == BacteriocinClass.CLASS_IIA_PEDIOCIN_LIKE
    assert confidence > 0.7


def test_descriptors_are_pure_functions_of_the_sequence() -> None:
    a = pep.describe_peptide(NISIN_A, 6.5)
    b = pep.describe_peptide(NISIN_A.lower(), 6.5)
    assert a == b
