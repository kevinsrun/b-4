"""The required computational simulation backend.

Pipeline for one spec
---------------------
1. resolve the candidate (inline, registry, or generic prior) and compute
   sequence-derived descriptors;
2. resolve the target organism against the curated priors;
3. resolve every condition, recording provided vs imputed;
4. compute the effective MIC and Hill cooperativity (``potency``);
5. integrate the coupled peptide/population ODEs for treated and control
   cultures (``kinetics``);
6. map the trajectory onto the readout of the requested assay type;
7. accumulate the uncertainty budget and run a local sensitivity analysis;
8. emit an ExperimentResult with full provenance and a mechanism trace.

Determinism: steps 1-7 contain no random number generation, and the ODE step
count is a pure function of the incubation time. Identical input gives
byte-identical output, which ``reproducibility.deterministic=True`` asserts.
"""

from __future__ import annotations

import math
from typing import Any

from bacteriocin_lab.agents.simulator import __version__ as CODE_VERSION
from bacteriocin_lab.agents.simulator._results import make_result_id, utc_now_iso
from bacteriocin_lab.agents.simulator.errors import SimulationError, SpecValidationError
from bacteriocin_lab.agents.simulator.model import environment as env
from bacteriocin_lab.agents.simulator.model import kinetics as kin
from bacteriocin_lab.agents.simulator.model import parameters as P
from bacteriocin_lab.agents.simulator.model import peptide as pep
from bacteriocin_lab.agents.simulator.model import potency as pot
from bacteriocin_lab.agents.simulator.model import uncertainty as unc
from bacteriocin_lab.agents.simulator.model.parameters import ParameterStore
from bacteriocin_lab.agents.simulator.schemas import (
    AssayDomain,
    AssayType,
    BacteriocinClass,
    CandidateSpec,
    EvidenceType,
    ExperimentResult,
    ExperimentSpec,
    ImportantFactor,
    Measurement,
    ParameterProvenance,
    ParameterSource,
    Reproducibility,
)

from .base import AdapterCapabilities, ExperimentAdapter

MODEL_NAME = "bacteriocin-sim"

class SimulationAdapter(ExperimentAdapter):
    """Mechanistic dose/density/environment simulator for bacteriocin activity."""

    name = "simulation"
    assay_domains = (AssayDomain.SIMULATED_IN_VITRO, AssayDomain.SIMULATED_IN_VIVO_LIKE)

    def __init__(
        self,
        *,
        parameter_overrides: dict[str, Any] | None = None,
        candidate_registry: dict[str, CandidateSpec] | None = None,
        validate_immediately: bool = False,
    ) -> None:
        self.parameter_overrides = parameter_overrides
        self.store = ParameterStore.from_overrides(parameter_overrides)
        self.candidate_registry = candidate_registry or {}
        if validate_immediately and parameter_overrides:
            self._ensure_validated()

    def _ensure_validated(self) -> None:
        """Validate parameter overrides against directional invariants before producing results."""
        from bacteriocin_lab.agents.simulator.validation import validate_parameter_configuration

        validate_parameter_configuration(
            parameter_overrides=self.parameter_overrides,
            store=self.store,
            model_version=self.model_version,
        )

    def run_batch(self, specs: list[ExperimentSpec]) -> list[ExperimentResult]:
        """Execute several experiments, validating parameter configuration first."""
        self._ensure_validated()
        return super().run_batch(specs)

    # ------------------------------------------------------------------
    # capability declaration
    # ------------------------------------------------------------------

    @property
    def model_version(self) -> str:
        """Fully-qualified version string embedded in every result."""
        return (
            f"{MODEL_NAME}/{CODE_VERSION}"
            f"+params.{self.store.version}"
            f"+{self.store.hash().split(':', 1)[1][:12]}"
        )

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            name=self.name,
            available=True,
            assay_domains=[d.value for d in self.assay_domains],
            assay_types=[a.value for a in AssayType],
            supported_conditions=[
                "bacteriocin_concentration (uM, nM, ug/mL with a molecular weight)",
                "target_cell_density (CFU/mL, cells/mL, OD600, log10 CFU/mL)",
                "producer_cell_density (in-situ production source)",
                "ph",
                "temperature_c",
                "medium",
                "ionic_conditions (NaCl, KCl, MgCl2, CaCl2, EDTA)",
                "incubation_time",
                "growth_phase",
                "assay_type",
                "permeabilizer",
                "target.resistance_factors",
                "candidate sequence / structural class / descriptors",
            ],
            evidence_type=EvidenceType.SIMULATION.value,
            deterministic=True,
            model_version=self.model_version,
            description=(
                "Mechanistic forward model: structure-activity potency on the log10 "
                "MIC scale, Langmuir peptide titration by target cells (inoculum "
                "effect), cooperative Hill occupancy, and coupled peptide-decay / "
                "kill / regrowth ODEs integrated to the assay readout."
            ),
            limitations=[
                "all prior parameters are coarse, uncalibrated literature estimates; "
                "predictions are hypothesis-generating, never confirmatory",
                "post-translational modifications are invisible to the sequence model, "
                "so lantibiotic structural class can only be inferred weakly",
                "two-peptide (class IIb) systems are modelled as a single peptide",
                "synergy between multiple bacteriocins is not modelled",
                "no spatial structure: agar diffusion assays are approximated from the "
                "well-mixed solution result",
                "strain-level variation is only represented through explicitly supplied "
                "resistance factors",
            ],
            requires=[
                "a candidate sequence or structural class for candidate-specific "
                "predictions (otherwise a generic peptide prior is used and flagged)"
            ],
        )

    # ------------------------------------------------------------------
    # main entry point
    # ------------------------------------------------------------------

    def run(self, spec: ExperimentSpec) -> ExperimentResult:
        """Simulate one experiment."""
        self._ensure_validated()
        self._check_domain(spec)
        ctx = self._build_context(spec)
        _, measurement, trace = self._evaluate(ctx, full=True)

        # The sensitivity analysis must run before the variance budget: the
        # budget propagates MIC uncertainty through the measured dose
        # derivative that the analysis produces.
        factors, derivatives = self._sensitivity(ctx)
        budget = self._build_budget(ctx, measurement)

        inhibition = measurement.predicted_inhibition_fraction or 0.0
        low, high = budget.interval(inhibition)
        measurement.uncertainty = round(budget.sigma_fraction(inhibition), 6)
        measurement.sigma_logit_inhibition = round(budget.total_sigma_logit, 4)
        measurement.ci95_inhibition_fraction = [round(low, 6), round(high, 6)]
        measurement.uncertainty_log10_reduction = round(
            budget.total_sigma_logit / math.log(10.0), 4
        )
        warnings = self._collect_warnings(ctx, measurement)

        result = ExperimentResult(
            result_id=make_result_id(spec, self.model_version),
            experiment_id=spec.experiment_id,
            hypothesis_id=spec.hypothesis_id,
            candidate_id=spec.candidate_id,
            conditions=self._canonical_conditions(ctx),
            measurement=measurement,
            important_factors=factors,
            evidence_type=EvidenceType.SIMULATION,
            model_version=self.model_version,
            warnings=warnings,
            status="ok",
            backend=self.name,
            assay_domain=ctx["resolved"].assay_domain,
            assay_type=ctx["resolved"].assay_type,
            confidence=budget.confidence(inhibition),
            uncertainty_components=budget.components,
            parameter_provenance=self._provenance(ctx),
            mechanism_trace=trace,
            reproducibility=Reproducibility(
                deterministic=True,
                spec_hash=spec.spec_hash(),
                parameter_set_hash=self.store.hash(),
                code_version=CODE_VERSION,
                random_seed=None,
            ),
            created_at=utc_now_iso(),
        )
        return result

    # ------------------------------------------------------------------
    # setup
    # ------------------------------------------------------------------

    def _check_domain(self, spec: ExperimentSpec) -> None:
        domain = spec.conditions.assay_domain
        value = domain.value if hasattr(domain, "value") else str(domain)
        if value not in {d.value for d in self.assay_domains}:
            raise SpecValidationError(
                f"the simulation backend cannot execute assay_domain={value!r}",
                details={
                    "experiment_id": spec.experiment_id,
                    "supported_assay_domains": [d.value for d in self.assay_domains],
                },
            )

    def _build_context(self, spec: ExperimentSpec) -> dict[str, Any]:
        """Resolve candidate, target and conditions into a single evaluation context."""
        warnings: list[str] = []
        candidate = self.resolve_candidate(spec, self.candidate_registry)

        if candidate is None or not candidate.sequence:
            if spec.candidate_id and candidate is None:
                warnings.append(
                    f"candidate_id {spec.candidate_id!r} could not be resolved to a "
                    "sequence (not inline and not in candidate_registry); a generic "
                    "small-bacteriocin prior was used, so this result is NOT specific "
                    "to that candidate"
                )
            elif candidate is None or not candidate.sequence:
                warnings.append(
                    "no candidate sequence was supplied; a generic small-bacteriocin "
                    "prior was used and uncertainty was inflated accordingly"
                )

        # target priors first: the OD600 conversion factor is organism-specific
        target_params, target_source, target_key = env.resolve_target(
            spec.target.species, self.store, warnings
        )

        # descriptors need a pH, and pH resolution needs nothing, so do a cheap
        # first pass with the eventual pH
        ph_for_descriptors = (
            spec.conditions.ph if spec.conditions.ph is not None else env.DEFAULTS["ph"]
        )
        seq = candidate.sequence if candidate else None
        descriptors = pep.describe_peptide(seq, ph_for_descriptors)
        descriptors = self._apply_supplied_descriptors(descriptors, candidate, warnings)

        bacteriocin_class = self._resolve_class(candidate, descriptors, warnings)
        cls_params, _ = pot.class_parameters(bacteriocin_class, self.store)

        mw = descriptors.molecular_weight_da
        if candidate is not None:
            mw = (
                candidate.molecular_weight_da
                or candidate.properties.molecular_weight_da
                or mw
            )

        resolved = env.resolve_conditions(
            spec.conditions,
            target_params=target_params,
            molecular_weight_da=mw,
            store=self.store,
        )
        warnings.extend(resolved.warnings)
        resolved.warnings = []

        if resolved.concentration_um <= 0.0 and resolved.producer_density_cfu_per_ml <= 0.0:
            warnings.append(
                "neither an exogenous bacteriocin concentration nor a producer cell "
                "density was supplied; this is a no-treatment control experiment"
            )

        self._check_biological_coherence(resolved, target_params, warnings)

        return {
            "spec": spec,
            "candidate": candidate,
            "descriptors": descriptors,
            "bacteriocin_class": bacteriocin_class,
            "class_params": cls_params,
            "target_params": target_params,
            "target_source": target_source,
            "target_key": target_key,
            "resolved": resolved,
            "molecular_weight_da": mw,
            "warnings": warnings,
        }

    def _apply_supplied_descriptors(
        self,
        descriptors: pep.PeptideDescriptors,
        candidate: CandidateSpec | None,
        warnings: list[str],
    ) -> pep.PeptideDescriptors:
        """Let caller-supplied descriptors override the sequence-derived ones."""
        if candidate is None:
            return descriptors
        props = candidate.properties
        supplied = {
            k: v
            for k, v in {
                "net_charge": props.net_charge,
                "hydrophobic_moment": props.hydrophobic_moment,
                "gravy": props.gravy,
                "molecular_weight_da": props.molecular_weight_da,
                "isoelectric_point": props.isoelectric_point,
            }.items()
            if v is not None
        }
        if not supplied:
            return descriptors
        if props.net_charge is not None and props.net_charge_ph is None:
            warnings.append(
                "candidate.properties.net_charge was supplied without net_charge_ph; "
                "it was assumed to apply at the experiment pH"
            )
        from dataclasses import replace

        updated = replace(descriptors, **supplied)
        if props.net_charge is not None:
            updated = replace(
                updated,
                net_charge_ph=props.net_charge_ph
                if props.net_charge_ph is not None
                else descriptors.net_charge_ph,
                # a supplied charge must not be recomputed from sequence
                sequence=descriptors.sequence,
            )
        return updated

    def _resolve_class(
        self,
        candidate: CandidateSpec | None,
        descriptors: pep.PeptideDescriptors,
        warnings: list[str],
    ) -> str:
        """Prefer a declared structural class over sequence inference."""
        declared = candidate.bacteriocin_class if candidate else None
        if declared:
            value = declared.value if hasattr(declared, "value") else str(declared)
            if value in self.store.classes:
                return value
            warnings.append(
                f"declared bacteriocin_class {value!r} is not a known class; the class "
                "was re-inferred from sequence"
            )
        inferred = descriptors.inferred_class
        if descriptors.is_generic_fallback:
            return BacteriocinClass.UNKNOWN.value
        if descriptors.class_inference_confidence < 0.3:
            warnings.append(
                f"structural class could only be guessed from sequence "
                f"({inferred.value}, confidence "
                f"{descriptors.class_inference_confidence:.2f}); supply "
                "candidate.bacteriocin_class for a sharper prediction"
            )
        return inferred.value

    def _check_biological_coherence(
        self,
        resolved: env.ResolvedConditions,
        target_params: dict[str, Any],
        warnings: list[str],
    ) -> None:
        """Flag condition sets that are internally incoherent.

        These are warnings, not errors: a planner may legitimately probe a
        boundary, and refusing to run would stall the loop. But a result at a
        temperature where the organism cannot grow means something different
        from an active bacteriocin, and the analysis agent must be told.
        """
        t = resolved.temperature_c
        t_min = float(target_params.get("t_min_c", 5.0))
        t_max = float(target_params.get("t_max_c", 45.0))
        if t <= t_min or t >= t_max:
            warnings.append(
                f"temperature {t} C is outside the growth range of this organism "
                f"({t_min}-{t_max} C): the control culture will not grow, so growth "
                "inhibition is not an interpretable readout here; use a time-kill "
                "assay instead"
            )
        ph = resolved.ph
        ph_min = float(target_params.get("ph_min", 4.5))
        ph_max = float(target_params.get("ph_max", 9.0))
        if ph <= ph_min or ph >= ph_max:
            warnings.append(
                f"pH {ph} is outside the growth range of this organism "
                f"({ph_min}-{ph_max}): growth inhibition is confounded by pH stress"
            )
        richness = float(resolved.medium_params.get("richness", 1.0) or 1.0)
        if richness < 0.1 and resolved.assay_type in (
            AssayType.MICROTITER_GROWTH_INHIBITION.value,
            AssayType.MIC_BROTH_MICRODILUTION.value,
        ):
            warnings.append(
                f"medium {resolved.medium!r} does not support growth, so a "
                f"{resolved.assay_type} readout is not meaningful; a time-kill assay "
                "is the appropriate design in a non-growth buffer"
            )
        if (
            resolved.aeration == "aerobic"
            and target_params.get("aerotolerance") == "obligate_anaerobe"
        ):
            warnings.append(
                "this organism is an obligate anaerobe and cannot be assayed "
                "aerobically; the predicted control growth is not achievable under "
                "the requested aeration"
            )
        if resolved.growth_phase == "biofilm":
            warnings.append(
                "biofilm populations are modelled only as a blanket tolerance factor; "
                "no spatial or matrix-diffusion effects are represented"
            )

    # ------------------------------------------------------------------
    # forward evaluation
    # ------------------------------------------------------------------

    def _evaluate(
        self, ctx: dict[str, Any], *, full: bool = False
    ) -> tuple[float, Measurement, dict[str, Any]]:
        """Run the forward model and build the measurement.

        Returns ``(response, measurement, mechanism_trace)`` where ``response``
        is ``logit(predicted_inhibition_fraction)`` -- the scalar the
        sensitivity analysis differentiates. The logit scale is used because it
        stays informative when the inhibition fraction saturates near 1, and
        because one logit unit is ~0.43 log10 of survival, which is how a
        microbiologist reads the effect size.
        """
        resolved: env.ResolvedConditions = ctx["resolved"]
        descriptors: pep.PeptideDescriptors = ctx["descriptors"]
        target_params: dict[str, Any] = ctx["target_params"]
        cls_params: dict[str, Any] = ctx["class_params"]
        store = self.store

        potency, resistance_applied = pot.effective_potency(
            descriptors,
            target_params,
            resolved,
            ctx["spec"].target.resistance_factors,
            ctx["bacteriocin_class"],
            store,
        )

        # medium availability reduces the peptide that is ever in solution
        availability = float(resolved.medium_params.get("availability", 1.0) or 1.0)
        effective_total_um = resolved.concentration_um * availability

        production_rate = 0.0
        if resolved.producer_density_cfu_per_ml > 0.0:
            production_rate = (
                store.g("production_rate_um_per_h_per_1e9cells")
                * resolved.producer_density_cfu_per_ml
                / 1.0e9
                * availability
            )

        f_t = env.cardinal_temperature_factor(
            resolved.temperature_c,
            float(target_params.get("t_min_c", 5.0)),
            float(target_params.get("t_opt_c", 37.0)),
            float(target_params.get("t_max_c", 45.0)),
        )
        f_ph = env.cardinal_ph_factor(
            resolved.ph,
            float(target_params.get("ph_min", 4.5)),
            float(target_params.get("ph_opt", 7.0)),
            float(target_params.get("ph_max", 9.0)),
        )
        richness = float(resolved.medium_params.get("richness", 1.0) or 1.0)
        growth_factor = f_t * f_ph * richness

        # Metabolically inactive cells are harder to kill: a peptide whose
        # mechanism depends on membrane potential or on lipid II cycling loses
        # efficacy when the target is not growing. Floor at 0.25 so that a
        # purely lytic mechanism still works on resting cells.
        metabolic_factor = 0.25 + 0.75 * min(1.0, f_t * f_ph)
        phase_susceptibility = (
            P.GROWTH_PHASE_SUSCEPTIBILITY.get(resolved.growth_phase, 1.0) * metabolic_factor
        )
        phase_rate = P.GROWTH_PHASE_RATE.get(resolved.growth_phase, 1.0)

        k_deg = env.peptide_decay_rate_per_h(
            resolved.temperature_c,
            resolved.ph,
            resolved.medium_params,
            float(cls_params.get("alkaline_lability", 1.0)),
            store,
        )

        k_input = kin.KineticsInput(
            mic_um=potency.mic_um,
            hill_coefficient=potency.hill_coefficient,
            initial_peptide_um=effective_total_um,
            initial_density_cfu_per_ml=resolved.target_density_cfu_per_ml,
            producer_density_cfu_per_ml=resolved.producer_density_cfu_per_ml,
            decay_rate_per_h=k_deg,
            mu_max_per_h=float(target_params.get("mu_max_per_h", 1.0)),
            growth_factor=growth_factor,
            phase_susceptibility=phase_susceptibility,
            phase_rate_factor=phase_rate,
            incubation_time_h=resolved.incubation_time_h,
            carrying_capacity=store.g("carrying_capacity_cfu_per_ml"),
            binding_sites_per_cell=store.g("binding_sites_per_cell"),
            kd_um=potency.mic_um * store.g("kd_over_mic"),
            resistant_fraction=store.g("resistant_subpopulation_fraction"),
            resistant_residual=store.g("resistant_residual_susceptibility"),
            kill_rate_max_per_h=store.g("k_max_per_h"),
            production_rate_um_per_h=production_rate,
        )

        try:
            out = kin.integrate(k_input, store)
        except (OverflowError, ValueError, ZeroDivisionError) as exc:
            raise SimulationError(
                f"population kinetics failed to integrate: {exc}",
                details={"mic_um": potency.mic_um, "conditions": resolved.__dict__.keys().__str__()},
            ) from exc

        inhibition_raw = 1.0 - out.survival_fraction_vs_control
        dose_over_mic = (
            out.mean_free_peptide_um / potency.mic_um if potency.mic_um > 0 else 0.0
        )
        # concentration-relative activity index, independent of incubation time
        activity = kin.hill_occupancy(
            out.mean_free_peptide_um, potency.mic_um, potency.hill_coefficient
        )

        measurement = Measurement(
            predicted_inhibition_fraction=round(min(1.0, max(0.0, inhibition_raw)), 6),
            predicted_survival_fraction=round(
                min(1.0, max(0.0, out.survival_fraction_vs_control)), 6
            ),
            predicted_activity=round(min(1.0, max(0.0, activity)), 6),
            uncertainty=None,
            primary_metric=self._primary_metric_name(resolved.assay_type),
            predicted_log10_reduction_vs_control=round(out.log10_reduction_vs_control, 4),
            predicted_log10_change_from_inoculum=round(out.log10_change_from_inoculum, 4),
            predicted_mic_um=round(potency.mic_um, 6),
            free_peptide_concentration_um=round(out.mean_free_peptide_um, 6),
            kill_rate_per_h=round(out.peak_kill_rate_per_h, 5),
            dose_over_mic=round(dose_over_mic, 5),
        )
        if resolved.assay_type in (
            AssayType.AGAR_WELL_DIFFUSION.value,
            AssayType.SPOT_ON_LAWN.value,
        ):
            measurement.predicted_zone_diameter_mm = round(
                self._zone_diameter_mm(effective_total_um, potency.mic_um), 3
            )

        # NB: the response is taken from the *unrounded* fraction. Rounding the
        # reported value to 6 decimals is right for a reported measurement but
        # would wipe out the gradient of any factor whose effect is small
        # relative to a saturated prediction, silently zeroing its sensitivity.
        response = unc.logit(min(1.0, max(0.0, inhibition_raw)))

        trace: dict[str, Any] = {}
        if full:
            trace = {
                "potency": {
                    "effective_mic_um": round(potency.mic_um, 6),
                    "log10_mic_um": round(potency.log10_mic_um, 4),
                    "term_breakdown_log10_mic": potency.terms,
                    "hill_coefficient": potency.hill_coefficient,
                    "receptor": potency.receptor,
                    "receptor_availability": potency.receptor_availability,
                    "electrostatic_factor": round(potency.electrostatic_factor, 4),
                    "resistance_factors_applied": resistance_applied,
                    "notes": potency.notes,
                },
                "peptide_descriptors": {
                    "length": descriptors.length,
                    "net_charge": descriptors.net_charge,
                    "net_charge_ph": descriptors.net_charge_ph,
                    "isoelectric_point": descriptors.isoelectric_point,
                    "gravy": descriptors.gravy,
                    "hydrophobic_moment": descriptors.hydrophobic_moment,
                    "molecular_weight_da": descriptors.molecular_weight_da,
                    "inferred_class": descriptors.inferred_class.value,
                    "class_inference_confidence": descriptors.class_inference_confidence,
                    "generic_fallback": descriptors.is_generic_fallback,
                    "notes": list(descriptors.notes),
                },
                "environment": {
                    "temperature_growth_factor": round(f_t, 4),
                    "ph_growth_factor": round(f_ph, 4),
                    "medium_richness": richness,
                    "medium_peptide_availability": availability,
                    "peptide_decay_rate_per_h": round(k_deg, 5),
                    "phase_susceptibility": round(phase_susceptibility, 4),
                    "ionic_strength_mm": round(resolved.ionic_strength_mm, 3),
                    "free_divalent_mm": round(resolved.divalent_mm, 3),
                    "in_situ_production_um_per_h": round(production_rate, 5),
                },
                "kinetics": {
                    "initial_cfu_per_ml": out.initial_cfu_per_ml,
                    "treated_final_cfu_per_ml": out.treated_final_cfu_per_ml,
                    "control_final_cfu_per_ml": out.control_final_cfu_per_ml,
                    "mean_occupancy": round(out.mean_occupancy, 6),
                    "regrowth_detected": out.regrowth_detected,
                    "trajectory": out.trajectory,
                },
            }
            ctx.setdefault("warnings", []).extend(potency.warnings)
            ctx.setdefault("warnings", []).extend(out.warnings)
            ctx["kinetics_out"] = out
            ctx["potency"] = potency

        return response, measurement, trace

    @staticmethod
    def _primary_metric_name(assay_type: str) -> str:
        return {
            AssayType.MIC_BROTH_MICRODILUTION.value: "predicted_mic_um",
            AssayType.MICROTITER_GROWTH_INHIBITION.value: "predicted_inhibition_fraction",
            AssayType.TIME_KILL.value: "predicted_log10_reduction_vs_control",
            AssayType.AGAR_WELL_DIFFUSION.value: "predicted_zone_diameter_mm",
            AssayType.SPOT_ON_LAWN.value: "predicted_zone_diameter_mm",
        }.get(assay_type, "predicted_inhibition_fraction")

    def _zone_diameter_mm(self, total_um: float, mic_um: float) -> float:
        """Zone of inhibition from radial diffusion.

        For diffusion from a well, the critical radius where the local
        concentration equals the MIC grows roughly with the logarithm of the
        applied-dose-to-MIC ratio. This is a coarse mapping of a well-mixed
        model onto a spatial assay and is flagged as such in the warnings.
        """
        if total_um <= 0 or mic_um <= 0:
            return 0.0
        ratio = total_um / mic_um
        if ratio <= 1.0:
            return 0.0
        base = self.store.g("zone_base_mm")
        return base + self.store.g("zone_diffusion_mm_per_log10") * math.log10(ratio)

    # ------------------------------------------------------------------
    # uncertainty, sensitivity, provenance
    # ------------------------------------------------------------------

    def _potency_sigma_logit(
        self, ctx: dict[str, Any], sigma_log10_mic: float
    ) -> tuple[float, str]:
        """Propagate the MIC-prior uncertainty by re-running the model at +/-1 sigma.

        A sigma-decade error in the predicted MIC is equivalent to a
        sigma-decade error in the applied dose with the opposite sign, so the
        spread is obtained by evaluating the response at ``dose * 10**(+/-sigma)``.
        A secant over the full uncertainty range is used rather than a local
        derivative because these priors span more than a decade, and a
        prediction that looks locally flat can be well off its plateau one
        sigma away.
        """
        resolved: env.ResolvedConditions = ctx["resolved"]
        dose = resolved.concentration_um
        if dose <= 0.0:
            return 0.0, (
                "no exogenous dose was applied, so the predicted outcome does not "
                "depend on the MIC prior"
            )
        sigma = max(sigma_log10_mic, 0.0)
        if sigma == 0.0:
            return 0.0, "the MIC prior was supplied with zero uncertainty"
        try:
            high = self._evaluate(
                self._perturbed_context(
                    ctx, "bacteriocin_concentration_um", dose * 10.0 ** sigma
                ),
                full=False,
            )[0]
            low = self._evaluate(
                self._perturbed_context(
                    ctx, "bacteriocin_concentration_um", dose * 10.0 ** -sigma
                ),
                full=False,
            )[0]
        except Exception as exc:  # pragma: no cover - defensive
            return sigma * 2.303, f"sigma propagation fell back to a nominal slope: {exc}"
        return abs(high - low) / 2.0, (
            "propagated by re-running the model with the dose shifted by "
            f"+/-{sigma:.2f} decades (equivalent to the same error in the MIC), "
            f"giving a logit response spread of {abs(high - low):.2f}"
        )

    def _build_budget(
        self,
        ctx: dict[str, Any],
        measurement: Measurement,
    ) -> unc.UncertaintyBudget:
        resolved: env.ResolvedConditions = ctx["resolved"]
        descriptors: pep.PeptideDescriptors = ctx["descriptors"]
        target_params: dict[str, Any] = ctx["target_params"]

        extra: list[tuple[str, float, str]] = []
        out: kin.KineticsOutput = ctx["kinetics_out"]
        if out.regrowth_detected:
            extra.append(
                (
                    "regrowth_timing",
                    0.60,
                    "the predicted outcome sits on the kill/regrowth boundary, where "
                    "small errors in kill rate or incubation time change the readout "
                    "qualitatively",
                )
            )
        if resolved.producer_density_cfu_per_ml > 0.0:
            extra.append(
                (
                    "in_situ_production_rate",
                    0.85,
                    "peptide production per producer cell is one of the least "
                    "constrained parameters in the model",
                )
            )
        if ctx["spec"].target.strain and ctx["target_source"] != ParameterSource.PROVIDED:
            extra.append(
                (
                    "strain_level_variation",
                    0.40,
                    f"a specific strain ({ctx['spec'].target.strain}) was requested but "
                    "priors are species-level; strain susceptibility varies widely",
                )
            )

        sigma_log10_mic = float(target_params.get("sigma_log10_mic", 0.8))

        # Ignorance about *which peptide* and *which organism* is uncertainty
        # about the MIC, so it widens the prior that gets propagated through
        # the model rather than being added to the total afterwards.
        #
        # This is what keeps the budget monotone in information. The response
        # is monotone in dose, so a wider +/-sigma window can only widen the
        # secant: withholding an input cannot now shrink the potency term. The
        # previous arrangement added these in logit space *beside* a secant
        # that was free to collapse, which is how a blind prediction could
        # come out more confident than an informed one.
        target_is_fallback = ctx["target_source"] == ParameterSource.FALLBACK_GENERIC
        peptide_is_generic = descriptors.is_generic_fallback
        mic_ignorance = [sigma_log10_mic]
        if peptide_is_generic:
            mic_ignorance.append(self.store.g("sigma_generic_peptide_log10_mic"))
        if target_is_fallback:
            mic_ignorance.append(self.store.g("sigma_unknown_target_log10_mic"))
        effective_sigma_log10_mic = math.sqrt(sum(s * s for s in mic_ignorance))

        potency_sigma, potency_rationale = self._potency_sigma_logit(
            ctx, effective_sigma_log10_mic
        )
        if effective_sigma_log10_mic > sigma_log10_mic:
            potency_rationale += (
                f"; the prior was widened from {sigma_log10_mic:.2f} to "
                f"{effective_sigma_log10_mic:.2f} decades because the MIC estimate "
                "rests on a generic peptide and/or an uncurated organism"
            )

        return unc.build_budget(
            store=self.store,
            target_sigma_log10_mic=effective_sigma_log10_mic,
            target_confidence=float(target_params.get("confidence", 0.3)),
            target_is_fallback=target_is_fallback,
            peptide_is_generic=peptide_is_generic,
            class_is_unknown=ctx["bacteriocin_class"] == BacteriocinClass.UNKNOWN.value,
            class_inference_confidence=descriptors.class_inference_confidence,
            n_imputed_conditions=len(resolved.imputed),
            domain_excursions=env.domain_excursions(resolved, self.store),
            potency_sigma_logit=potency_sigma,
            potency_rationale=potency_rationale,
            medium_confidence=float(resolved.medium_params.get("confidence", 0.4)),
            extra=extra,
        )

    def _sensitivity(
        self, ctx: dict[str, Any]
    ) -> tuple[list[ImportantFactor], dict[str, float]]:
        """Perturb each condition and re-run the forward model."""
        resolved: env.ResolvedConditions = ctx["resolved"]
        base = float(self._evaluate(dict(ctx), full=False)[0])

        factors = {
            "bacteriocin_concentration_um": resolved.concentration_um,
            "target_cell_density_cfu_per_ml": resolved.target_density_cfu_per_ml,
            "ph": resolved.ph,
            "temperature_c": resolved.temperature_c,
            "incubation_time_h": resolved.incubation_time_h,
            "ionic_strength_mm": resolved.ionic_strength_mm,
            "divalent_cation_mm": resolved.divalent_mm,
        }
        if resolved.producer_density_cfu_per_ml > 0:
            factors["producer_cell_density_cfu_per_ml"] = (
                resolved.producer_density_cfu_per_ml
            )

        sources = {p.name: p.source for p in resolved.provenance}
        sources.setdefault("divalent_cation_mm", ParameterSource.IMPUTED_DEFAULT)

        def evaluate(name: str, value: float) -> float:
            perturbed = self._perturbed_context(ctx, name, value)
            return float(self._evaluate(perturbed, full=False)[0])

        return unc.local_sensitivity(evaluate, base, factors, sources)

    def _perturbed_context(
        self, ctx: dict[str, Any], name: str, value: float
    ) -> dict[str, Any]:
        """Shallow-copy the context with one resolved condition changed."""
        from copy import copy

        resolved: env.ResolvedConditions = ctx["resolved"]
        new_resolved = copy(resolved)
        new_resolved.medium_params = dict(resolved.medium_params)
        new_resolved.provenance = list(resolved.provenance)
        new_resolved.imputed = list(resolved.imputed)
        new_resolved.warnings = []

        mapping = {
            "bacteriocin_concentration_um": "concentration_um",
            "target_cell_density_cfu_per_ml": "target_density_cfu_per_ml",
            "producer_cell_density_cfu_per_ml": "producer_density_cfu_per_ml",
            "ph": "ph",
            "temperature_c": "temperature_c",
            "incubation_time_h": "incubation_time_h",
            "ionic_strength_mm": "ionic_strength_mm",
            "divalent_cation_mm": "divalent_mm",
        }
        attr = mapping.get(name)
        if attr is None:
            raise SimulationError(f"unknown sensitivity factor {name!r}")
        setattr(new_resolved, attr, max(0.0, float(value)) if attr != "ph" else float(value))

        new_ctx = dict(ctx)
        new_ctx["resolved"] = new_resolved
        new_ctx["warnings"] = []

        # pH changes the peptide's net charge, so descriptors must be recomputed
        if name == "ph":
            descriptors: pep.PeptideDescriptors = ctx["descriptors"]
            if descriptors.sequence:
                new_ctx["descriptors"] = pep.describe_peptide(
                    descriptors.sequence, float(value)
                )
        return new_ctx

    def _provenance(self, ctx: dict[str, Any]) -> list[ParameterProvenance]:
        """Record where every model input came from."""
        resolved: env.ResolvedConditions = ctx["resolved"]
        descriptors: pep.PeptideDescriptors = ctx["descriptors"]
        out: list[ParameterProvenance] = []

        for item in resolved.provenance:
            out.append(
                ParameterProvenance(
                    parameter=item.name,
                    value=item.value,
                    source=item.source,
                    evidence_type=EvidenceType.DATABASE
                    if item.source == ParameterSource.PROVIDED
                    else EvidenceType.MODEL_PREDICTED,
                    reference=item.reference,
                )
            )

        out.append(
            ParameterProvenance(
                parameter="target_organism_priors",
                value={
                    "matched_key": ctx["target_key"],
                    "log10_mic_um_base": ctx["target_params"].get("log10_mic_um_base"),
                    "sigma_log10_mic": ctx["target_params"].get("sigma_log10_mic"),
                    "confidence": ctx["target_params"].get("confidence"),
                    "notes": ctx["target_params"].get("notes"),
                },
                source=ctx["target_source"],
                evidence_type=EvidenceType.DATABASE,
                reference=f"curated prior set {self.store.version}",
            )
        )
        out.append(
            ParameterProvenance(
                parameter="peptide_descriptors",
                value={
                    "length": descriptors.length,
                    "net_charge": descriptors.net_charge,
                    "hydrophobic_moment": descriptors.hydrophobic_moment,
                },
                source=ParameterSource.FALLBACK_GENERIC
                if descriptors.is_generic_fallback
                else ParameterSource.SEQUENCE_DERIVED,
                evidence_type=EvidenceType.MODEL_PREDICTED,
                reference="Kyte-Doolittle / Eisenberg scales; Henderson-Hasselbalch charge",
            )
        )
        out.append(
            ParameterProvenance(
                parameter="bacteriocin_class",
                value=ctx["bacteriocin_class"],
                source=ParameterSource.PROVIDED
                if (ctx["candidate"] and ctx["candidate"].bacteriocin_class)
                else ParameterSource.HEURISTIC_INFERENCE,
                evidence_type=EvidenceType.MODEL_PREDICTED,
                reference="sequence-motif heuristic" if not (
                    ctx["candidate"] and ctx["candidate"].bacteriocin_class
                ) else "declared by the caller",
            )
        )
        out.append(
            ParameterProvenance(
                parameter="medium_properties",
                value={
                    "medium": resolved.medium,
                    "availability": resolved.medium_params.get("availability"),
                    "protease_activity": resolved.medium_params.get("protease_activity"),
                    "richness": resolved.medium_params.get("richness"),
                },
                source=ParameterSource.CURATED_PRIOR,
                evidence_type=EvidenceType.DATABASE,
                reference=f"curated medium set {self.store.version}",
            )
        )
        return out

    def _collect_warnings(
        self, ctx: dict[str, Any], measurement: Measurement
    ) -> list[str]:
        """Deduplicate warnings and append the mandatory provenance caveat."""
        warnings = list(dict.fromkeys(ctx.get("warnings", [])))
        resolved: env.ResolvedConditions = ctx["resolved"]

        if resolved.assay_type in (
            AssayType.AGAR_WELL_DIFFUSION.value,
            AssayType.SPOT_ON_LAWN.value,
        ):
            warnings.append(
                "zone diameter is extrapolated from a well-mixed model; no agar "
                "diffusion, peptide retention or colony-lawn geometry is simulated"
            )
        if (measurement.predicted_mic_um or 0.0) >= 1e4:
            warnings.append(
                "the predicted MIC hit the model's upper clamp; interpret only as "
                "'no activity predicted', not as a quantitative MIC"
            )
        warnings.append(
            "SIMULATION-DERIVED RESULT: produced by a mechanistic model built on "
            "uncalibrated literature priors. It is a hypothesis to be tested, not "
            "an experimental observation, and must not be reported as validated."
        )
        return warnings

    def _canonical_conditions(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Echo back the fully-resolved conditions in contract field names.

        The result's ``conditions`` block carries the values the model actually
        used -- with units normalised and defaults filled in -- so a downstream
        agent never has to guess what an omitted field became.
        """
        resolved: env.ResolvedConditions = ctx["resolved"]
        spec: ExperimentSpec = ctx["spec"]
        return {
            "bacteriocin_concentration": {
                "value": round(resolved.concentration_um, 6),
                "unit": "uM",
            },
            "target_cell_density": {
                "value": resolved.target_density_cfu_per_ml,
                "unit": "cfu_per_ml",
            },
            "producer_cell_density": {
                "value": resolved.producer_density_cfu_per_ml,
                "unit": "cfu_per_ml",
            },
            "ph": resolved.ph,
            "temperature_c": resolved.temperature_c,
            "medium": resolved.medium,
            "ionic_conditions": {
                "ionic_strength_mm": round(resolved.ionic_strength_mm, 3),
                "free_divalent_mm": round(resolved.divalent_mm, 3),
                "edta_mm": resolved.edta_mm,
            },
            "incubation_time": resolved.incubation_time_h,
            "incubation_time_unit": "h",
            "growth_phase": resolved.growth_phase,
            "assay_domain": resolved.assay_domain,
            "assay_type": resolved.assay_type,
            "target": {
                "species": spec.target.species,
                "strain": spec.target.strain,
                "resistance_factors": [
                    f.to_json_dict() for f in spec.target.resistance_factors
                ],
            },
            "imputed_fields": list(resolved.imputed),
        }
