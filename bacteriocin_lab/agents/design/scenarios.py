"""Environmental robustness scenario analysis for bacteriocin candidates.

Addresses P2:
- Contextual stresses and target matrix effects:
  1. standard_in_vitro (baseline reference)
  2. high_density_infection (inoculum effect + physiological ionic screening)
  3. acidic_food_matrix (acid stability, cold-chain preservation)
  4. high_fat_dairy (lipid binding and matrix sequestration)
  5. protease_challenge (sequence-based cleavage scanning & RiPP protection)
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

# Kyte & Doolittle hydropathy scale
KYTE_DOOLITTLE: dict[str, float] = {
    "A": 1.8,
    "R": -4.5,
    "N": -3.5,
    "D": -3.5,
    "C": 2.5,
    "Q": -3.5,
    "E": -3.5,
    "G": -0.4,
    "H": -3.2,
    "I": 4.5,
    "L": 3.8,
    "K": -3.9,
    "M": 1.9,
    "F": 2.8,
    "P": -1.6,
    "S": -0.8,
    "T": -0.7,
    "W": -0.9,
    "Y": -1.3,
    "V": 4.2,
}


class ScenarioProfile(BaseModel):
    """Activity and stability profile across a specific environmental matrix."""

    model_config = ConfigDict(extra="ignore")

    scenario_id: str
    scenario_name: str
    description: str
    predicted_activity_retention: float = Field(
        ...,
        ge=0.0,
        le=1.5,
        description="Relative activity retention (1.0 = unchanged vs standard in vitro)",
    )
    limiting_factors: list[str] = Field(default_factory=list)
    matrix_effects: dict[str, Any] = Field(default_factory=dict)
    feasibility: str = Field(
        ..., description="'high_suitability', 'moderate_suitability', or 'poor_suitability'"
    )


def compute_gravy(sequence: str) -> float:
    """Calculate Grand Average of Hydropathicity (GRAVY)."""
    seq = sequence.upper().strip()
    if not seq:
        return 0.0
    total = sum(KYTE_DOOLITTLE.get(aa, 0.0) for aa in seq)
    return round(total / len(seq), 3)


def count_protease_cleavage_sites(sequence: str) -> tuple[int, int]:
    """Count trypsin (K/R not followed by P) and chymotrypsin (F/Y/W/L not followed by P) sites."""
    seq = sequence.upper().strip()
    trypsin_sites = 0
    chymotrypsin_sites = 0
    length = len(seq)

    for i in range(length):
        aa = seq[i]
        next_aa = seq[i + 1] if i + 1 < length else ""
        if next_aa == "P":
            continue

        if aa in ("K", "R"):
            trypsin_sites += 1
        elif aa in ("F", "Y", "W", "L"):
            chymotrypsin_sites += 1

    return trypsin_sites, chymotrypsin_sites


def evaluate_environmental_scenarios(
    sequence: str,
    bacteriocin_class: str | None = None,
    candidate_name: str | None = None,
    target_organism: str = "Listeria monocytogenes",
) -> list[ScenarioProfile]:
    """Evaluate candidate peptide across 5 standardized environmental/matrix scenarios.

    1. standard_in_vitro (neutral pH, low cell density, minimal matrix)
    2. high_density_infection (pH 7.2, 1e8 CFU/mL, 150 mM NaCl ionic screening)
    3. acidic_food_matrix (pH 4.2, 4°C, dairy/fermented food model)
    4. high_fat_dairy (lipophilic sequestration into fat emulsion)
    5. protease_challenge (endogenous and digestive protease stability)
    """
    seq = sequence.upper().strip()
    cls_lower = (bacteriocin_class or "").lower().strip()
    name_lower = (candidate_name or "").lower().strip()

    gravy = compute_gravy(seq)
    trypsin_sites, chymotrypsin_sites = count_protease_cleavage_sites(seq)
    net_charge = sum(1 for aa in seq if aa in ("K", "R")) - sum(1 for aa in seq if aa in ("D", "E"))

    is_lantibiotic = cls_lower == "class_i" or "lantibiotic" in cls_lower or "nisin" in name_lower
    is_lasso = "lasso" in cls_lower or "class_v" in cls_lower or "microcin j" in name_lower
    is_pediocin_like = cls_lower == "class_iia" or "pediocin" in name_lower

    scenarios: list[ScenarioProfile] = []

    # 1. Standard In Vitro Baseline
    scenarios.append(
        ScenarioProfile(
            scenario_id="standard_in_vitro",
            scenario_name="Standard In Vitro Assay",
            description="Reference conditions: pH 6.5, 37°C, 1e6 CFU/mL, Mueller-Hinton/BHI broth.",
            predicted_activity_retention=1.00,
            limiting_factors=[],
            matrix_effects={"ph": 6.5, "ionic_strength_mm": 50, "cell_density_cfu_ml": 1e6},
            feasibility="high_suitability",
        )
    )

    # 2. High Density Infection (Inoculum effect + ionic screening)
    # Target density 1e8 CFU/mL titrates peptide; 150 mM NaCl screens electrostatic attraction
    density_penalty = 0.35  # Severe inoculum effect
    charge_resilience = min(0.15, max(0.0, net_charge * 0.03))
    retention_infection = max(0.15, round(1.0 - density_penalty + charge_resilience - 0.10, 2))
    infection_factors = [
        "Inoculum effect: 100-fold higher target cell density titrates available peptide.",
        "Ionic screening: 150 mM physiological NaCl attenuates membrane docking.",
    ]
    if net_charge <= 0:
        infection_factors.append(
            "Low net cationic charge makes candidate highly vulnerable to ionic screening."
        )

    scenarios.append(
        ScenarioProfile(
            scenario_id="high_density_infection",
            scenario_name="High-Density In Vivo / Infection Model",
            description="Infection conditions: pH 7.2, 37°C, 1e8 CFU/mL, 150 mM NaCl.",
            predicted_activity_retention=retention_infection,
            limiting_factors=infection_factors,
            matrix_effects={
                "cell_density_cfu_ml": 1e8,
                "ionic_strength_mm": 150,
                "inoculum_titration_risk": "high",
            },
            feasibility="moderate_suitability"
            if retention_infection >= 0.50
            else "poor_suitability",
        )
    )

    # 3. Acidic Food Matrix (pH 4.2, refrigerated)
    # Lantibiotics and Class IIa are famously acid-stable; solubility and protonation increase.
    if is_lantibiotic or is_pediocin_like:
        retention_acid = 1.10  # Enhanced stability & solubility at acidic pH
        acid_factors = [
            "Acidic pH enhances cationic solubility and prevents basic peptide aggregation."
        ]
    else:
        retention_acid = 0.90
        acid_factors = ["Moderate acid stability under food preservation conditions."]

    scenarios.append(
        ScenarioProfile(
            scenario_id="acidic_food_matrix",
            scenario_name="Acidic Fermented Food Preservation",
            description="Food matrix conditions: pH 4.2, 4°C, fermented dairy/meat preservation.",
            predicted_activity_retention=retention_acid,
            limiting_factors=acid_factors,
            matrix_effects={"ph": 4.2, "temperature_c": 4.0, "acid_stability": "high"},
            feasibility="high_suitability",
        )
    )

    # 4. High-Fat Dairy Matrix (Sequestration)
    # Hydrophobic peptides partition into fat globules, reducing free active concentration.
    # Higher GRAVY = more sequestration
    fat_sequestration_loss = min(0.65, max(0.10, (gravy + 1.0) * 0.25))
    retention_fat = round(max(0.20, 1.0 - fat_sequestration_loss), 2)
    fat_factors = [
        f"Peptide GRAVY score of {gravy:+.2f} leads to partitioning into lipid droplets.",
        "Free aqueous concentration reduced due to binding to milk fat triglycerides.",
    ]
    scenarios.append(
        ScenarioProfile(
            scenario_id="high_fat_dairy",
            scenario_name="High-Fat Dairy / Lipid Emulsion",
            description="Emulsion matrix: 10% milk fat emulsion, pH 6.7, room temperature.",
            predicted_activity_retention=retention_fat,
            limiting_factors=fat_factors,
            matrix_effects={
                "gravy": gravy,
                "lipid_partitioning_risk": "high" if gravy > 0.0 else "moderate",
            },
            feasibility="high_suitability" if retention_fat >= 0.70 else "moderate_suitability",
        )
    )

    # 5. Protease Challenge
    # Lasso peptides have extreme resistance; lantibiotics protected; linear cleaved.
    if is_lasso:
        retention_protease = 0.95
        protease_factors = ["Lasso peptide macrolactam knot confers exceptional steric protection."]
        feasibility = "high_suitability"
    elif is_lantibiotic:
        retention_protease = 0.75
        protease_factors = [
            f"Lanthionine rings provide partial steric shielding against trypsin "
            f"({trypsin_sites} putative sites)."
        ]
        feasibility = "moderate_suitability"
    else:
        # Linear or Class IIa
        cleavage_burden = trypsin_sites + 0.5 * chymotrypsin_sites
        loss = min(0.80, cleavage_burden * 0.08)
        retention_protease = round(max(0.15, 1.0 - loss), 2)
        protease_factors = [
            f"Linear peptide exposes {trypsin_sites} trypsin and {chymotrypsin_sites} "
            f"chymotrypsin cleavage sites to degradation."
        ]
        feasibility = (
            "high_suitability"
            if retention_protease >= 0.65
            else ("moderate_suitability" if retention_protease >= 0.40 else "poor_suitability")
        )

    scenarios.append(
        ScenarioProfile(
            scenario_id="protease_challenge",
            scenario_name="Proteolytic Degradation Challenge",
            description="Protease challenge: Trypsin/chymotrypsin exposure.",
            predicted_activity_retention=retention_protease,
            limiting_factors=protease_factors,
            matrix_effects={
                "trypsin_cleavage_sites": trypsin_sites,
                "chymotrypsin_cleavage_sites": chymotrypsin_sites,
                "structural_protection": "lasso_knot"
                if is_lasso
                else ("thioether_rings" if is_lantibiotic else "none"),
            },
            feasibility=feasibility,
        )
    )

    return scenarios
