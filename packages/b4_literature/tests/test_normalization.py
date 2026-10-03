from b4_literature.normalization import normalize_concentration, normalize_time


def test_mass_concentration_normalizes_without_molecular_assumptions() -> None:
    result = normalize_concentration("2.5", "mg/L")
    assert result.normalized_value == 2.5
    assert result.normalized_unit == "µg/mL"


def test_molar_concentration_preserves_original_unit() -> None:
    result = normalize_concentration("4", "µM")
    assert result.normalized_value is None
    assert result.original_unit == "µM"
    assert "requires additional" in result.normalization_note


def test_time_normalizes_to_hours() -> None:
    assert normalize_time("90", "minutes").normalized_value == 1.5
