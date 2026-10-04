#!/usr/bin/env python3
"""Worked examples of the Candidate Generation & Design Agent.

Run from the repository root::

    PYTHONPATH=src python3 examples/generate_candidates.py

Four scenarios, each showing something the agent is meant to do:

1. A cold start against a Gram-positive target.
2. The same request after a result comes back -- the ranking must move.
3. Competing hypotheses in play -- discrimination starts to matter.
4. A Gram-negative target -- the accessibility penalty changes the winner.
"""

from __future__ import annotations

import json

from bacteriocin_lab.agents.candidate import (  # noqa: E402
    CandidateGenerationAgent,
    CandidateRequest,
)


def show(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def summarise(result, *, show_detail: bool = False) -> None:
    print(f"\nConsidered {result.considered_count}, returned {len(result.candidates)}.\n")
    for candidate in result.candidates:
        score = candidate.score
        print(f"  #{candidate.rank}  {candidate.name}")
        print(f"      id            {candidate.candidate_id}")
        print(f"      origin        {candidate.origin}  ({candidate.validation_status})")
        print(
            f"      total {score.total:.3f}  = promise {score.promise:.2f} "
            f"| novelty {score.novelty:.2f} | uncert {score.uncertainty:.2f} "
            f"| info-gain {score.information_gain:.2f} "
            f"| discrim {score.hypothesis_discrimination:.2f} "
            f"| cond-fit {score.condition_fit:.2f}"
        )
        print(f"      worth testing {candidate.confidence:.3f}")
        if candidate.features.computed:
            computed = candidate.features.computed
            print(
                f"      {computed.sequence_length} aa, "
                f"{computed.molecular_weight:.1f} Da, "
                f"charge {computed.net_charge:+.2f} @ pH {computed.charge_ph}, "
                f"GRAVY {computed.gravy:+.2f}"
            )
        print(f"      hypothesis    {candidate.hypothesis}")
        if show_detail:
            primary = candidate.hypotheses[0]
            print(f"      falsified if  {primary.falsified_if}")
            for strength in candidate.expected_strengths[:2]:
                print(f"      strength      {strength}")
            for mode in candidate.expected_failure_modes[:2]:
                print(f"      failure mode  {mode}")
        print()


def main() -> None:
    agent = CandidateGenerationAgent()

    # ------------------------------------------------------------------
    show("1. Cold start: Listeria monocytogenes, pH 6.0-7.5, 1e8 CFU/mL")

    base = {
        "research_objective": {
            "goal": "Find a bacteriocin that inhibits L. monocytogenes in a "
            "refrigerated ready-to-eat food matrix."
        },
        "target": {
            "organism": "Listeria monocytogenes",
            "strain": "EGD-e",
            "gram": "positive",
        },
        "desired_behavior": {
            "high_inhibition": True,
            "ph_range": [6.0, 7.5],
            "target_cell_density": 100_000_000,
            "temperature_c": 37,
            "assay_domain": "simulated_in_vitro",
        },
        "constraints": {"max_candidates": 4, "diversity_weight": 0.3},
    }

    first = agent.run(CandidateRequest.model_validate(base))
    summarise(first, show_detail=True)
    print("Selection logic:")
    print(f"  {first.selection_logic}\n")
    print("Uncertainties the agent is explicit about:")
    for uncertainty in first.uncertainties:
        print(f"  [{uncertainty.severity}] {uncertainty.kind}: {uncertainty.description}")

    # ------------------------------------------------------------------
    show("2. After a simulation result: the ranking must change")

    top = first.candidates[0]
    print(f"\nFeeding back a simulated result for {top.name} ({top.candidate_id}).")
    print("Note this is 'simulation-derived', NOT experimental validation.\n")

    with_result = dict(base)
    with_result["previous_results"] = [
        {
            "result_id": "res_demo_1",
            "experiment_id": "exp_demo_1",
            "candidate_id": top.candidate_id,
            "measurement": {
                "predicted_inhibition_fraction": 0.82,
                "predicted_survival_fraction": 0.18,
                "uncertainty": 0.1,
            },
            "important_factors": ["bacteriocin_concentration", "target_cell_density"],
            "evidence_type": "simulation-derived",
            "model_version": "simulation/0.1.0",
        }
    ]

    second = agent.run(CandidateRequest.model_validate(with_result))
    summarise(second)

    before = {c.candidate_id: c for c in first.candidates}
    for candidate in second.candidates:
        previous = before.get(candidate.candidate_id)
        if previous and previous.score.novelty != candidate.score.novelty:
            print(
                f"  {candidate.name}: novelty {previous.score.novelty:.2f} "
                f"-> {candidate.score.novelty:.2f}, total "
                f"{previous.score.total:.3f} -> {candidate.score.total:.3f}"
            )

    # ------------------------------------------------------------------
    show("3. With competing hypotheses: discrimination starts to matter")

    with_hypotheses = dict(base)
    with_hypotheses["competing_hypotheses"] = [
        {
            "hypothesis_id": "hyp_charge_driven",
            "statement": "Activity is limited by electrostatic association, so high "
            "net positive charge is required.",
            "discriminating_feature": "net_charge",
            "favourable_range": [3.0, 12.0],
            "confidence": 0.5,
        },
        {
            "hypothesis_id": "hyp_hydrophobicity_driven",
            "statement": "Activity is limited by membrane insertion, so net charge is "
            "largely irrelevant.",
            "discriminating_feature": "net_charge",
            "favourable_range": [-5.0, 1.0],
            "confidence": 0.5,
        },
    ]
    with_hypotheses["constraints"] = {
        "max_candidates": 4,
        "diversity_weight": 0.3,
        "scoring_weights": {"promise": 0.25, "hypothesis_discrimination": 0.35},
    }

    third = agent.run(CandidateRequest.model_validate(with_hypotheses))
    summarise(third)
    print("Candidates that split the two hypotheses score above 0 on discrimination;")
    print("candidates both hypotheses agree on cannot settle the question.\n")

    # ------------------------------------------------------------------
    show("4. Gram-negative target: outer-membrane access changes the answer")

    gram_negative = {
        "research_objective": {"goal": "Inhibit E. coli in a simulated gut-like context."},
        "target": {"organism": "Escherichia coli", "strain": "K-12", "gram": "negative"},
        "desired_behavior": {
            "high_inhibition": True,
            "ph_range": [6.5, 7.5],
            "target_cell_density": 1_000_000,
            "temperature_c": 37,
            "assay_domain": "simulated_in_vivo_like",
        },
        "constraints": {"max_candidates": 3, "diversity_weight": 0.2},
    }
    summarise(agent.run(CandidateRequest.model_validate(gram_negative)))

    # ------------------------------------------------------------------
    show("5. The Omnigent-facing envelope")

    envelope = agent.run_envelope(base)
    print(
        json.dumps(
            {
                "agent": envelope.agent,
                "confidence": envelope.confidence,
                "model_version": envelope.model_version,
                "artifacts": envelope.artifacts,
                "recommended_next_action": envelope.recommended_next_action.model_dump(mode="json"),
                "warnings": envelope.warnings,
                "candidate_count": len(envelope.decision["candidates"]),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
