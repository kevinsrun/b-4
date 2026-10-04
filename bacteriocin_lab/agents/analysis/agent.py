"""The Result Analysis Agent.

One responsibility: say what an ``ExperimentResult`` *means* -- whether it
supports, weakens, or fails to distinguish the hypothesis it was meant to test,
how it compares with earlier experiments, which variables drove it, what was
unexpected, and how sure that interpretation is.

It does not run experiments, does not choose the next one (it recommends
``experiment_planner`` and hands over structured hints), and does not write the
knowledge base (it emits structured claims for the Knowledge Agent). It never
describes a simulation-derived or model-predicted result as experimentally
validated, and never emits ``wet-lab-derived`` evidence of its own.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from bacteriocin_lab.shared.contract import (
    AgentResponseEnvelope,
    Evidence,
    RecommendedNextAction,
    Uncertainty,
)
from bacteriocin_lab.shared.ids import evidence_id as make_evidence_id
from bacteriocin_lab.shared.ids import finding_id as make_finding_id
from bacteriocin_lab.shared.ids import run_id as make_run_id

from .adapters import is_failed_attempt, normalize_payload
from .comparison import (
    LABELS,
    MIN_EFFECT,
    ComparisonOutcome,
    SeriesVerdict,
    compare,
    inhibition_of,
    sigma_details,
    sigma_of,
)
from .hypothesis import HypothesisVerdict, evaluate
from .schema import (
    Driver,
    HypothesisUnderTest,
    ResultAnalysis,
    ResultAnalysisRequest,
    UnexpectedResult,
    VariableFinding,
)

logger = logging.getLogger(__name__)

AGENT_NAME = "result_analysis_agent"

#: Bump on any change that can alter output for identical input.
MODEL_VERSION = "result-analysis/0.1.0"

#: Words in important_factors strings that identify a variable.
_FACTOR_KEYWORDS: dict[str, tuple[str, ...]] = {
    "bacteriocin_concentration": ("concentration", "dose"),
    "target_cell_density": ("density", "inoculum", "cell number"),
    "producer_cell_density": ("producer",),
    "ph": ("ph",),
    "temperature_c": ("temperature", "temp"),
    "incubation_time": ("incubation", "time"),
}

_VALIDATION_CLAIM = re.compile(
    r"\b(?:experimentally|empirically)\s+(?:validated|confirmed|verified|proven|demonstrated)\b"
    r"|\bwet-?lab[- ](?:validated|confirmed|verified)\b",
    re.IGNORECASE,
)
#: A negation within the same clause, shortly before the phrase, makes it a disclaimer ("NOT experimentally validated").
_NEGATION_BEFORE = re.compile(
    r"\b(?:not|never|no|nothing|none|without|cannot|nor|isn't|aren't|neither)\b[^.;:]{0,30}$",
    re.IGNORECASE,
)


def claims_experimental_validation(text: str) -> bool:
    """True when ``text`` asserts (rather than disclaims) experimental validation."""
    for m in _VALIDATION_CLAIM.finditer(text):
        if not _NEGATION_BEFORE.search(text[max(0, m.start() - 40) : m.start()]):
            return True
    return False


class AnalysisIntegrityError(RuntimeError):
    """Raised when a draft analysis would misdescribe the provenance of a result."""


@dataclass
class AnalysisOutcome:
    """Everything produced for one result; ``run_envelope`` serialises this."""

    analysis: ResultAnalysis
    evidence: list[Evidence]
    warnings: list[str]
    artifacts: dict[str, Any]
    recommended_next_action: RecommendedNextAction


class ResultAnalysisAgent:
    """Tool-callable result interpretation agent.

    Stateless: ``analyze`` is a pure function of its request. Everything it
    knows about earlier experiments arrives in ``previous_results`` and
    ``research_state``, so a finding can be reconstructed from its inputs.
    """

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def analyze(self, request: ResultAnalysisRequest) -> AnalysisOutcome:
        result = request.result
        warnings: list[str] = []
        hypothesis = self._resolve_hypothesis(request, warnings)
        prior = self._collect_prior(request)
        outcome = compare(result, prior)
        verdict = evaluate(hypothesis, outcome, result)

        findings = self._findings(result, outcome, hypothesis, verdict)
        unexpected = self._unexpected(result, outcome, verdict, findings)
        drivers = self._drivers(result, findings)
        uncertainties = self._uncertainties(result, outcome, verdict, findings, hypothesis)
        confidence, breakdown = self._confidence(
            result, verdict, outcome, findings, unexpected, hypothesis
        )
        followups, suggestions = self._followups(
            result, outcome, verdict, findings, unexpected, hypothesis
        )

        wet = result.is_experimentally_validated
        analysis = ResultAnalysis(
            finding_id=make_finding_id(
                experiment_id=result.experiment_id,
                hypothesis_id=hypothesis.hypothesis_id if hypothesis else None,
                result_id=result.result_id,
                model_version=MODEL_VERSION,
            ),
            experiment_id=result.experiment_id,
            result_id=result.result_id,
            candidate_id=result.candidate_id,
            hypothesis_id=hypothesis.hypothesis_id if hypothesis else None,
            hypothesis_status=verdict.status,  # type: ignore[arg-type]
            evidence_strength=verdict.strength,  # type: ignore[arg-type]
            status_basis=verdict.basis,
            prediction_source=verdict.source,
            findings=findings,
            unexpected_results=unexpected,
            drivers=drivers,
            confidence=confidence,
            uncertainties=uncertainties,
            recommended_followup_questions=followups,
            observed=self._observed(result, outcome),
            source_evidence_type=result.evidence_type,
            provenance_note=(
                "This result is wet-lab-derived; interpretations describe measured behaviour."
                if wet
                else f"This result is {result.evidence_type}. Interpretations describe the behaviour of the "
                "model/simulator that produced it and are NOT experimentally validated."
            ),
            model_version=MODEL_VERSION,
        )
        self._assert_provenance_language(analysis, wet)

        warnings.extend(self._warnings(result, outcome, verdict))
        evidence = self._evidence(analysis, result, outcome, wet)
        artifacts = {
            "run_id": make_run_id(request.model_dump(mode="json")),
            "confidence_breakdown": breakdown,
            "comparisons": self._comparison_records(outcome),
            "knowledge_update": self._knowledge_update(analysis, evidence),
            "planner_hints": self._planner_hints(analysis, verdict, suggestions, unexpected),
            "prior_results_used": [r.result_id for r in outcome.usable_prior],
        }
        return AnalysisOutcome(
            analysis,
            evidence,
            sorted(set(warnings)),
            artifacts,
            self._next_action(analysis, artifacts),
        )

    def run_envelope(self, payload: dict[str, Any]) -> AgentResponseEnvelope:
        """JSON-in / JSON-out entry point for Omnigent. Never raises across the tool boundary."""
        payload = normalize_payload(payload)  # accept the simulator's richer result shape
        if isinstance(payload, dict) and is_failed_attempt(payload.get("result")):
            return self._failed_attempt(payload["result"], payload.get("hypothesis"))
        try:
            request = ResultAnalysisRequest.model_validate(payload)
        except Exception as exc:
            logger.warning("Invalid request to %s: %s", AGENT_NAME, exc)
            return self._failure(
                f"Request did not validate against ResultAnalysisRequest: {exc}", "high"
            )
        try:
            out = self.analyze(request)
        except AnalysisIntegrityError as exc:
            logger.error("Integrity guard tripped: %s", exc)
            return self._failure(f"Analysis withheld by the provenance guard: {exc}", "high")
        except Exception as exc:
            logger.exception("Result analysis failed")
            return self._failure(f"Internal analysis error: {type(exc).__name__}: {exc}", "high")
        return AgentResponseEnvelope(
            agent=AGENT_NAME,
            decision=out.analysis.model_dump(mode="json"),
            evidence=out.evidence,
            confidence=out.analysis.confidence,
            uncertainties=list(out.analysis.uncertainties),
            artifacts=out.artifacts,
            warnings=out.warnings,
            recommended_next_action=out.recommended_next_action,
            model_version=MODEL_VERSION,
        )

    @staticmethod
    def _failed_attempt(raw: dict[str, Any], hypothesis: Any) -> AgentResponseEnvelope:
        """A failed run is a failed attempt, never a negative finding (it has no measurement)."""
        err = raw.get("error") or {}
        reason = err.get("message") or err.get("type") or "no error detail supplied"
        hid = (
            hypothesis.get("hypothesis_id")
            if isinstance(hypothesis, dict)
            else raw.get("hypothesis_id")
        )
        eid, rid = str(raw.get("experiment_id", "unknown")), str(raw.get("result_id", "unknown"))
        analysis = ResultAnalysis(
            finding_id=make_finding_id(
                experiment_id=eid, hypothesis_id=hid, result_id=rid, model_version=MODEL_VERSION
            ),
            experiment_id=eid,
            result_id=rid,
            candidate_id=str(raw.get("candidate_id") or "unknown"),
            hypothesis_id=hid,
            hypothesis_status="inconclusive",
            evidence_strength="none",
            status_basis=f"The experiment attempt failed ({reason}). A failed attempt carries no measurement, so it says nothing for or against the hypothesis; it is not a negative finding.",
            prediction_source="none",
            uncertainties=[
                Uncertainty(
                    kind="data-gap",
                    severity="high",
                    affects=[x for x in (eid, rid, hid) if x],
                    description=f"No measurement exists for {eid}: {reason}",
                )
            ],
            recommended_followup_questions=[
                f"Why did {eid} fail ({reason})? Fix the specification or backend and re-run before drawing any conclusion about {hid or 'the hypothesis'}."
            ],
            source_evidence_type=str(raw.get("evidence_type", "simulation-derived")),
            provenance_note="No result was produced; nothing was interpreted.",
            model_version=MODEL_VERSION,
        )
        return AgentResponseEnvelope(
            agent=AGENT_NAME,
            decision=analysis.model_dump(mode="json"),
            confidence=0.0,
            uncertainties=list(analysis.uncertainties),
            warnings=[f"Failed attempt {eid}: {reason}"],
            artifacts={"failed_attempt": True, "knowledge_update": None},
            recommended_next_action=RecommendedNextAction(
                agent="experiment_planner",
                reason="The attempt failed and produced no evidence; re-plan or repair the specification rather than treating this as a negative result.",
                payload_hint={
                    "failed_experiment_id": eid,
                    "hypothesis_id": hid,
                    "hypothesis_status": "inconclusive",
                },
            ),
            model_version=MODEL_VERSION,
        )

    @staticmethod
    def _failure(message: str, severity: str) -> AgentResponseEnvelope:
        return AgentResponseEnvelope(
            agent=AGENT_NAME,
            decision={
                "hypothesis_status": "inconclusive",
                "findings": [],
                "status_basis": "Analysis could not be performed.",
            },
            confidence=0.0,
            uncertainties=[Uncertainty(kind="data-gap", description=message, severity=severity)],  # type: ignore[arg-type]
            warnings=[message],
            model_version=MODEL_VERSION,
        )

    # ------------------------------------------------------------------
    # Inputs
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_hypothesis(
        request: ResultAnalysisRequest, warnings: list[str]
    ) -> HypothesisUnderTest | None:
        if request.hypothesis is not None:
            return request.hypothesis
        hid = (request.spec.hypothesis_id if request.spec else None) or request.result.hypothesis_id
        if not hid:
            return None
        pool = request.research_state.get("hypotheses")
        entries = list(pool.values()) if isinstance(pool, dict) else list(pool or [])
        for entry in entries:
            if isinstance(entry, dict) and entry.get("hypothesis_id") == hid:
                try:
                    return HypothesisUnderTest.model_validate(entry)
                except Exception as exc:
                    warnings.append(f"Hypothesis {hid} in research_state did not validate: {exc}")
                    return None
        warnings.append(
            f"Hypothesis {hid} was referenced but not supplied; only condition-response analysis was possible."
        )
        return HypothesisUnderTest(hypothesis_id=hid)

    @staticmethod
    def _collect_prior(request: ResultAnalysisRequest) -> list[Any]:
        prior: list[Any] = list(request.previous_results)
        stored = request.research_state.get("results")
        prior.extend(list(stored.values()) if isinstance(stored, dict) else list(stored or []))
        return prior

    # ------------------------------------------------------------------
    # Findings
    # ------------------------------------------------------------------

    @staticmethod
    def _interpret(variable: str, v: SeriesVerdict, wet: bool) -> str:
        label = LABELS.get(variable, variable)
        noun = "measured" if wet else "predicted"
        span = ""
        if v.delta is not None and len(v.points) >= 2:
            lo, hi = v.points[0], v.points[-1]
            unit = (
                " (log10 axis)"
                if variable
                in ("bacteriocin_concentration", "target_cell_density", "producer_cell_density")
                else ""
            )
            span = f" (inhibition {lo.y:.2f} -> {hi.y:.2f} as {label} goes {lo.raw:g} -> {hi.raw:g}{unit}; n={v.n_points}, other conditions held fixed)"
        text = {
            "negative": f"Higher {label} is associated with reduced {noun} inhibition{span}.",
            "positive": f"Higher {label} is associated with increased {noun} inhibition{span}.",
            "none": f"No detectable change in {noun} inhibition across the compared {label} range{span}.",
            "non_monotonic": f"{noun.capitalize()} inhibition does not change monotonically with {label}{span}.",
            "unresolved": f"The change in {noun} inhibition with {label} is too uncertain to call{span}.",
        }[v.relationship]
        if v.plateau:
            text += " The response flattens at the high end (saturation)."
        return text

    def _findings(
        self, result, outcome: ComparisonOutcome, hypothesis, verdict: HypothesisVerdict
    ) -> list[VariableFinding]:
        wet = result.is_experimentally_validated
        out: list[VariableFinding] = []
        for var, v in outcome.verdicts.items():
            out.append(
                VariableFinding(
                    variable=var,
                    relationship=v.relationship,  # type: ignore[arg-type]
                    effect_size=None if v.effect_size is None else round(v.effect_size, 4),
                    interpretation=self._interpret(var, v, wet),
                    delta_inhibition=None if v.delta is None else round(v.delta, 4),
                    z_score=None if v.z is None else round(v.z, 2),
                    n_points=v.n_points,
                    controlled=True,
                    plateau=v.plateau,
                    compared_result_ids=[p.result_id for p in v.points],
                )
            )
        # The hypothesis's own variable must always appear, even when nothing could be said about it.
        hv = verdict.variable
        if hv and hv not in outcome.verdicts:
            noun = "measured" if wet else "predicted"
            out.append(
                VariableFinding(
                    variable=hv,
                    relationship="unresolved",
                    interpretation=f"No earlier result differs from this one in {LABELS.get(hv, hv)} alone, so its effect on {noun} inhibition cannot be isolated.",
                    n_points=1,
                    controlled=False,
                    compared_result_ids=[result.result_id],
                )
            )
        out.sort(
            key=lambda f: (
                -(abs(f.delta_inhibition) if f.delta_inhibition is not None else -1),
                f.variable,
            )
        )
        return out

    # ------------------------------------------------------------------
    # Unexpected results
    # ------------------------------------------------------------------

    def _unexpected(
        self,
        result,
        outcome: ComparisonOutcome,
        verdict: HypothesisVerdict,
        findings: list[VariableFinding],
    ) -> list[UnexpectedResult]:
        out: list[UnexpectedResult] = []
        m = result.measurement
        if (
            m.predicted_inhibition_fraction is not None
            and m.predicted_survival_fraction is not None
        ):
            gap = abs(m.predicted_inhibition_fraction + m.predicted_survival_fraction - 1.0)
            if gap > 0.02:
                out.append(
                    UnexpectedResult(
                        kind="inconsistent_measurement",
                        description=f"inhibition ({m.predicted_inhibition_fraction:.2f}) and survival ({m.predicted_survival_fraction:.2f}) do not sum to 1 (off by {gap:.2f}); the producing model may be inconsistent.",
                        severity="high",
                        refs=[result.result_id],
                    )
                )
        if verdict.prediction_mismatch:
            out.append(
                UnexpectedResult(
                    kind="prediction_mismatch",
                    description=verdict.prediction_mismatch + ".",
                    severity="medium",
                    refs=[result.result_id],
                )
            )

        opposite = {"positive": "negative", "negative": "positive"}
        for var, prior_v in outcome.prior_only.items():
            now = outcome.verdicts.get(var)
            if now is None or prior_v.relationship not in opposite:
                continue
            if (
                now.relationship == opposite[prior_v.relationship]
                or now.relationship == "non_monotonic"
            ):
                out.append(
                    UnexpectedResult(
                        kind="contradicts_prior_trend",
                        description=f"Earlier results showed a {prior_v.relationship} {LABELS.get(var, var)} relationship, but adding {result.result_id} makes it {now.relationship}.",
                        severity="high",
                        refs=[p.result_id for p in now.points],
                    )
                )
        for f in findings:
            if f.relationship == "non_monotonic" and not any(
                (u.kind == "contradicts_prior_trend"
                and f.variable in u.description)
                or LABELS.get(f.variable, "") in u.description
                for u in out
            ):
                out.append(
                    UnexpectedResult(
                        kind="non_monotonic_response",
                        description=f"Inhibition is non-monotonic in {LABELS.get(f.variable, f.variable)}; a simple dose/condition trend does not hold.",
                        severity="medium",
                        refs=f.compared_result_ids,
                    )
                )

        listed = self._factor_variables(result.important_factors)
        controlled_effects = {f.variable: f for f in findings if f.controlled}
        for var in listed:
            f = controlled_effects.get(var)
            if f is not None and f.relationship == "none":
                out.append(
                    UnexpectedResult(
                        kind="driver_mismatch",
                        description=f"The producer flagged {LABELS.get(var, var)} as important, but the controlled comparison shows no detectable effect of it.",
                        severity="low",
                        refs=f.compared_result_ids,
                    )
                )
        if listed:
            for f in findings:
                if (
                    f.relationship in ("positive", "negative")
                    and f.variable not in listed
                    and abs(f.delta_inhibition or 0) >= 2 * MIN_EFFECT
                    and f.z_score
                    and abs(f.z_score) >= 4
                ):
                    out.append(
                        UnexpectedResult(
                            kind="driver_mismatch",
                            description=f"{LABELS.get(f.variable, f.variable)} has a strong controlled effect (delta {f.delta_inhibition:+.2f}) but is not among the producer's important_factors.",
                            severity="low",
                            refs=f.compared_result_ids,
                        )
                    )
        return out

    @staticmethod
    def _factor_variables(factors: list[str]) -> list[str]:
        found: list[str] = []
        for text in factors:
            low = str(text).lower()
            for var, words in _FACTOR_KEYWORDS.items():
                if var not in found and any(
                    re.search(rf"\b{re.escape(w)}\b", low) or (w in low and len(w) > 4) for w in words
                ):
                    found.append(var)
        return found

    def _drivers(self, result, findings: list[VariableFinding]) -> list[Driver]:
        listed = self._factor_variables(result.important_factors)
        ranked = [
            f
            for f in findings
            if f.relationship in ("positive", "negative", "non_monotonic") and f.controlled
        ]
        ranked.sort(key=lambda f: -abs(f.delta_inhibition or 0))
        drivers: list[Driver] = []
        for f in ranked:
            drivers.append(
                Driver(
                    variable=f.variable,
                    rank=len(drivers) + 1,
                    basis="both" if f.variable in listed else "controlled-comparison",
                    delta_inhibition=f.delta_inhibition,
                )
            )
        for var in listed:
            if not any(d.variable == var for d in drivers):
                drivers.append(
                    Driver(variable=var, rank=len(drivers) + 1, basis="simulator-important-factors")
                )
        return drivers

    # ------------------------------------------------------------------
    # Uncertainty, confidence, follow-ups
    # ------------------------------------------------------------------

    def _uncertainties(
        self, result, outcome: ComparisonOutcome, verdict: HypothesisVerdict, findings, hypothesis
    ) -> list[Uncertainty]:
        u: list[Uncertainty] = []
        ids = [result.result_id] + ([hypothesis.hypothesis_id] if hypothesis else [])
        if not result.is_experimentally_validated:
            u.append(
                Uncertainty(
                    kind="model-limitation",
                    severity="medium",
                    affects=ids,
                    description=f"The result is {result.evidence_type}: it reflects the producing model, not a measurement on real cells. Every conclusion here needs wet-lab validation before real-world use.",
                )
            )
        sigma, defaulted, sigma_note = sigma_details(result)
        if sigma_note:
            u.append(
                Uncertainty(
                    kind="model-limitation",
                    severity="medium",
                    affects=[result.result_id],
                    description=sigma_note[0].upper() + sigma_note[1:] + ".",
                )
            )
        if defaulted:
            u.append(
                Uncertainty(
                    kind="data-gap",
                    severity="medium",
                    affects=[result.result_id],
                    description=f"The result reports no measurement uncertainty; {sigma} was assumed for significance tests, so z-scores are indicative only.",
                )
            )
        elif sigma > 0.2:
            u.append(
                Uncertainty(
                    kind="aleatoric",
                    severity="high",
                    affects=[result.result_id],
                    description=f"The uncertainty on inhibition ({sigma:.2f}) is large; many differences cannot be resolved.",
                )
            )
        y = inhibition_of(result)
        if y is not None and (y >= 0.98 or y <= 0.02):
            alt = (result.measurement.model_extra or {}).get("predicted_log10_reduction_vs_control")
            hint = (
                f" Compare predicted_log10_reduction_vs_control ({alt:.2f}) instead."
                if isinstance(alt, int | float)
                else ""
            )
            u.append(
                Uncertainty(
                    kind="model-limitation",
                    severity="medium",
                    affects=[result.result_id],
                    description=f"Inhibition {y:.2f} sits at the {'ceiling' if y >= 0.98 else 'floor'}; the assay has no dynamic range here, so comparisons at this point understate differences.{hint}",
                )
            )
        imputed = list((result.conditions.model_extra or {}).get("imputed_fields") or [])
        imputed += [
            d.get("factor")
            for d in (result.model_extra or {}).get("important_factor_details", [])
            if d.get("source") not in (None, "provided")
        ]
        if imputed:
            u.append(
                Uncertainty(
                    kind="data-gap",
                    severity="medium",
                    affects=[result.result_id],
                    description=f"The producer filled in defaults for {', '.join(sorted({str(i) for i in imputed}))}; the result describes assumed values for those, not specified ones. Treat it as provisional until they are pinned down.",
                )
            )
        components = [
            c
            for c in (result.model_extra or {}).get("uncertainty_components", [])
            if isinstance(c, dict) and isinstance(c.get("sigma_logit"), int | float)
        ]
        if components:
            top = max(components, key=lambda c: c["sigma_logit"])
            u.append(
                Uncertainty(
                    kind="epistemic",
                    severity="medium",
                    affects=[result.result_id],
                    description=f"The largest named source of model uncertainty is {top.get('source')} (sigma_logit {top['sigma_logit']:.2f}); a confident-looking number may mostly reflect that prior.",
                )
            )
        if not any(f.controlled and f.n_points >= 2 for f in findings):
            u.append(
                Uncertainty(
                    kind="data-gap",
                    severity="high",
                    affects=[result.result_id],
                    description="No earlier result for this candidate differs from this one in a single variable, so no condition-response relationship could be isolated.",
                )
            )
        for f in findings:
            if (
                f.controlled
                and f.n_points == 2
                and f.relationship in ("positive", "negative", "none")
            ):
                u.append(
                    Uncertainty(
                        kind="epistemic",
                        severity="medium",
                        affects=f.compared_result_ids,
                        description=f"The {LABELS.get(f.variable, f.variable)} relationship rests on two points; its shape (linear, saturating, threshold) is unknown.",
                    )
                )
        if (
            result.conditions.bacteriocin_concentration is not None
            and not result.conditions.concentration_unit
        ):
            u.append(
                Uncertainty(
                    kind="contract-gap",
                    severity="low",
                    affects=[result.result_id],
                    description="Concentration has no unit on this result; comparisons assume all results share one unit.",
                )
            )
        for text in outcome.unit_mismatches + outcome.skipped:
            u.append(
                Uncertainty(
                    kind="data-gap", severity="low", affects=[result.result_id], description=text
                )
            )
        for r in outcome.defaulted_sigma_ids:
            if r != result.result_id:
                u.append(
                    Uncertainty(
                        kind="data-gap",
                        severity="low",
                        affects=[r],
                        description=f"Prior result {r} reports no uncertainty; {0.05} was assumed.",
                    )
                )
        if verdict.source == "statement-keyword-heuristic":
            u.append(
                Uncertainty(
                    kind="model-limitation",
                    severity="medium",
                    affects=ids,
                    description="The expected relationship was inferred from the hypothesis statement text with a keyword rule; supply expected_relationship for a reliable test.",
                )
            )
        if verdict.status == "inconclusive" and verdict.source == "none":
            u.append(
                Uncertainty(
                    kind="data-gap", severity="medium", affects=ids, description=verdict.basis
                )
            )
        return u

    def _confidence(
        self, result, verdict, outcome, findings, unexpected, hypothesis
    ) -> tuple[float, dict[str, float]]:
        sigma, _ = sigma_of(result)
        strength = {"none": 0.0, "weak": 0.08, "moderate": 0.18, "strong": 0.25}[verdict.strength]
        controlled = [f for f in findings if f.controlled and f.n_points >= 2]
        has_hyp_series = (
            any(f.variable == verdict.variable for f in controlled)
            if verdict.variable
            else bool(controlled)
        )
        parts = {
            "base": 0.35,
            "hypothesis_evidence_strength": strength,
            "controlled_comparison_on_hypothesis_variable": 0.15 if has_hyp_series else 0.0,
            "additional_controlled_series": 0.05
            * min(2, max(0, len(controlled) - (1 if has_hyp_series else 0))),
            "measurement_uncertainty_penalty": -0.2 * min(1.0, sigma / 0.3),
            "unexpected_high_severity_penalty": -0.1
            * min(2, sum(1 for u in unexpected if u.severity == "high")),
            "heuristic_prediction_penalty": -0.05
            if verdict.source == "statement-keyword-heuristic"
            else 0.0,
        }
        raw = sum(parts.values())
        cap = (
            0.95 if result.is_experimentally_validated else 0.85
        )  # simulation-derived results never earn near-certainty
        parts["cap"] = cap
        return round(min(cap, max(0.05, raw)), 3), {k: round(v, 3) for k, v in parts.items()}

    def _followups(
        self, result, outcome, verdict, findings, unexpected, hypothesis
    ) -> tuple[list[str], list[dict[str, Any]]]:
        q: list[str] = []
        suggestions: list[dict[str, Any]] = []
        cond = result.conditions.model_dump()

        def suggest(var: str, reason: str) -> None:
            raw = cond.get(var)
            if raw is None:
                values: list[Any] = []
            elif var in (
                "bacteriocin_concentration",
                "target_cell_density",
                "producer_cell_density",
            ):
                values = [raw / 100, raw * 100] if raw else []
            elif var == "ph":
                values = [max(0.0, round(raw - 1.5, 2)), min(14.0, round(raw + 1.5, 2))]
            else:
                values = [raw * 0.5, raw * 2]
            suggestions.append(
                {
                    "candidate_id": result.candidate_id,
                    "vary": var,
                    "suggested_values": values,
                    "hold_fixed": f"all other conditions as in {result.experiment_id}",
                    "reason": reason,
                }
            )

        hv = verdict.variable
        label = LABELS.get(hv or "", hv or "the hypothesised variable")
        if (
            hypothesis
            and verdict.status == "inconclusive"
            and hv
            and not any(f.variable == hv and f.controlled for f in findings)
        ):
            q.append(
                f"Re-run {result.candidate_id} changing only {label} to isolate its effect on inhibition."
            )
            suggest(hv, "isolate the hypothesis variable; no controlled comparison exists")
        elif hypothesis and verdict.status == "inconclusive":
            q.append(
                f"Is the {label} effect real? Add a point with a larger {label} contrast or reduce measurement uncertainty."
            )
            if hv:
                suggest(hv, "effect not distinguishable from uncertainty")
        if verdict.status == "weakened":
            q.append(
                f"If {hypothesis.hypothesis_id if hypothesis else 'the hypothesis'} is wrong, what alternative explanation accounts for the observed inhibition? Test the next-largest driver."
            )
            for d in [
                f
                for f in findings
                if f.relationship in ("positive", "negative") and f.variable != hv
            ][:1]:
                suggest(d.variable, "alternative explanation for the weakened hypothesis")
        if verdict.status == "supported":
            two_point = [
                f for f in findings if f.controlled and f.n_points == 2 and f.variable == hv
            ]
            if two_point:
                q.append(
                    f"Is the {label} response monotonic and where does it saturate? Add an intermediate and an extreme {label} point."
                )
                suggest(hv, "supported on two points; characterise the shape")
        for f in findings:
            if f.plateau:
                q.append(
                    f"The response to {LABELS.get(f.variable, f.variable)} saturates; is the plateau a model ceiling or a real limit, and can another variable lift it?"
                )
        for u in unexpected:
            if u.kind == "contradicts_prior_trend":
                q.append(
                    "A previous trend reversed: repeat the contrasting conditions with other seeds/replicates, and check for a hidden interaction with the variable that differs."
                )
            elif u.kind == "non_monotonic_response":
                q.append(
                    "The response is non-monotonic: sample more densely across the range to locate the turning point."
                )
            elif u.kind == "prediction_mismatch":
                q.append(
                    "The result is far from the hypothesis's predicted inhibition: should the prior (and the model behind it) be revised?"
                )
            elif u.kind == "inconsistent_measurement":
                q.append(
                    "The inhibition and survival readouts disagree: audit the simulation/assay output before using this result."
                )
        if not result.is_experimentally_validated:
            q.append(
                "Does this simulated relationship hold in a wet-lab assay? Any wet-lab test is a consequential action and needs human approval."
            )
        seen: set[str] = set()
        return [x for x in q if not (x in seen or seen.add(x))], suggestions

    # ------------------------------------------------------------------
    # Outputs
    # ------------------------------------------------------------------

    @staticmethod
    def _observed(result, outcome: ComparisonOutcome) -> dict[str, Any]:
        m = result.measurement
        return {
            "predicted_inhibition_fraction": m.predicted_inhibition_fraction,
            "predicted_survival_fraction": m.predicted_survival_fraction,
            "predicted_activity": m.predicted_activity,
            "uncertainty": m.uncertainty,
            "conditions": {
                k: v for k, v in result.conditions.model_dump().items() if v not in (None, {}, [])
            },
            "n_prior_results_used": len(outcome.usable_prior),
            "n_controlled_series": len(outcome.verdicts),
        }

    @staticmethod
    def _warnings(result, outcome: ComparisonOutcome, verdict: HypothesisVerdict) -> list[str]:
        w = list(result.warnings)
        if not result.is_experimentally_validated:
            w.append(
                "PROVENANCE: interpreting a non-wet-lab result; nothing here is experimentally validated."
            )
        w.extend(outcome.skipped)
        w.extend(outcome.unit_mismatches)
        w.extend(verdict.notes)
        return w

    @staticmethod
    def _comparison_records(outcome: ComparisonOutcome) -> list[dict[str, Any]]:
        return [
            {
                "variable": var,
                "relationship": v.relationship,
                "n_points": v.n_points,
                "delta_inhibition": None if v.delta is None else round(v.delta, 4),
                "effect_size_per_unit": None if v.effect_size is None else round(v.effect_size, 4),
                "z": None if v.z is None else round(v.z, 2),
                "plateau": v.plateau,
                "points": [
                    {
                        "result_id": p.result_id,
                        "value": p.raw,
                        "inhibition": p.y,
                        "sigma": p.sigma,
                        "sigma_assumed": p.sigma_defaulted,
                    }
                    for p in v.points
                ],
            }
            for var, v in sorted(outcome.verdicts.items())
        ]

    def _evidence(
        self, analysis: ResultAnalysis, result, outcome: ComparisonOutcome, wet: bool
    ) -> list[Evidence]:
        """Interpretations are 'inferred-hypothesis' evidence: this agent never mints wet-lab evidence."""
        source = f"{AGENT_NAME}/{MODEL_VERSION} analysing {result.result_id}"
        subjects = [
            x
            for x in (
                analysis.candidate_id,
                analysis.hypothesis_id,
                analysis.experiment_id,
                analysis.result_id,
            )
            if x
        ]
        items: list[tuple[str, list[str], str | None]] = []
        if analysis.hypothesis_id:
            items.append(
                (
                    f"Hypothesis {analysis.hypothesis_id} is {analysis.hypothesis_status} by {analysis.experiment_id} ({analysis.evidence_strength} evidence): {analysis.status_basis}",
                    [],
                    analysis.hypothesis_id,
                )
            )
        for f in analysis.findings:
            if f.relationship != "unresolved":
                items.append((f.interpretation, f.compared_result_ids, None))
        out: list[Evidence] = []
        for claim, extra, _ in items:
            tagged = f"[{analysis.source_evidence_type}] {claim}"
            out.append(
                Evidence(
                    evidence_id=make_evidence_id(
                        claim=tagged, source=source, evidence_type="inferred-hypothesis"
                    ),
                    evidence_type="inferred-hypothesis",
                    claim=tagged,
                    source=source,
                    confidence=analysis.confidence,
                    subject_ids=sorted(set(subjects + extra)),
                    notes=analysis.provenance_note,
                    derived_from_evidence_type=analysis.source_evidence_type,
                    finding_id=analysis.finding_id,
                )
            )
        return out

    @staticmethod
    def _knowledge_update(analysis: ResultAnalysis, evidence: list[Evidence]) -> dict[str, Any]:
        return {
            "finding_id": analysis.finding_id,
            "hypothesis_update": None
            if not analysis.hypothesis_id
            else {
                "hypothesis_id": analysis.hypothesis_id,
                "status": analysis.hypothesis_status,
                "evidence_strength": analysis.evidence_strength,
                "confidence": analysis.confidence,
            },
            "claim_evidence_ids": [e.evidence_id for e in evidence],
            "relationships": [
                {
                    "variable": f.variable,
                    "relationship": f.relationship,
                    "effect_size": f.effect_size,
                    "controlled": f.controlled,
                }
                for f in analysis.findings
            ],
            "contradictions": [
                u.model_dump()
                for u in analysis.unexpected_results
                if u.kind in ("contradicts_prior_trend", "prediction_mismatch")
            ],
            "source_evidence_type": analysis.source_evidence_type,
            "is_experimentally_validated": analysis.source_evidence_type == "wet-lab-derived",
        }

    @staticmethod
    def _planner_hints(
        analysis: ResultAnalysis,
        verdict: HypothesisVerdict,
        suggestions: list[dict[str, Any]],
        unexpected: list[UnexpectedResult],
    ) -> dict[str, Any]:
        reopen = []
        if analysis.hypothesis_id and (
            any(u.kind in ("contradicts_prior_trend", "prediction_mismatch") for u in unexpected)
        ):
            reopen.append(analysis.hypothesis_id)
        return {
            "hypothesis_id": analysis.hypothesis_id,
            "hypothesis_status": analysis.hypothesis_status,
            "evidence_strength": analysis.evidence_strength,
            "resolved_variables": [
                f.variable
                for f in analysis.findings
                if f.controlled
                and f.relationship in ("positive", "negative", "none")
                and abs(f.z_score or 0) >= 2
            ],
            "unresolved_variables": [
                f.variable
                for f in analysis.findings
                if f.relationship in ("unresolved", "non_monotonic")
            ],
            "reopen_hypothesis_ids": reopen,
            "suggested_experiments": suggestions,
            "followup_questions": analysis.recommended_followup_questions,
            "interpretation_confidence": analysis.confidence,
        }

    @staticmethod
    def _next_action(analysis: ResultAnalysis, artifacts: dict[str, Any]) -> RecommendedNextAction:
        status = analysis.hypothesis_status
        reason = {
            "supported": "Hypothesis supported by this result; choose the next test from the follow-up questions and remaining open hypotheses.",
            "weakened": "Hypothesis weakened; the planner should shift to an alternative explanation rather than repeat this design.",
            "inconclusive": "Result did not separate the outcomes; the planner should add a controlled comparison before drawing conclusions.",
        }[status]
        return RecommendedNextAction(
            agent="experiment_planner",
            reason=reason,
            payload_hint={
                **artifacts["planner_hints"],
                "also_notify": ["knowledge_agent"],
                "knowledge_update": artifacts["knowledge_update"],
            },
        )

    @staticmethod
    def _assert_provenance_language(analysis: ResultAnalysis, wet: bool) -> None:
        """Fail closed if any generated sentence would claim experimental validation of a non-wet-lab result."""
        if wet:
            return
        for text in _strings(analysis.model_dump(mode="json")):
            if claims_experimental_validation(text):
                raise AnalysisIntegrityError(
                    f"draft text claims experimental validation of a {analysis.source_evidence_type} result: {text[:120]!r}"
                )


def _strings(obj: Any):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, list | tuple):
        for v in obj:
            yield from _strings(v)


_DEFAULT_AGENT: ResultAnalysisAgent | None = None


def analyze_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Omnigent-callable entry point: JSON in, contract-shaped JSON out. Never raises.

    Register as an Omnigent tool (the agent is stateless, so one instance is reused)::

        omnigent.register_tool(name="analyze_result", fn=analyze_result)
    """
    global _DEFAULT_AGENT
    if _DEFAULT_AGENT is None:
        _DEFAULT_AGENT = ResultAnalysisAgent()
    return _DEFAULT_AGENT.run_envelope(payload).model_dump(mode="json")


__all__ = [
    "AGENT_NAME",
    "MODEL_VERSION",
    "AnalysisIntegrityError",
    "AnalysisOutcome",
    "ResultAnalysisAgent",
    "analyze_result",
    "claims_experimental_validation",
]
