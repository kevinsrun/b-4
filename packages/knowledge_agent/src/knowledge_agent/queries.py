"""Read-only views over the research state. Every answer is built from recorded history, never from memory."""

from __future__ import annotations

from collections import Counter
from typing import Any

from bacteriocin_shared import ResearchState

from .errors import NotFound
from .reducer import DECISIVE_RELATIONSHIPS


def _dump(model: Any) -> Any:
    return model.model_dump(mode="json")


def get_candidate_history(state: ResearchState, candidate_id: str) -> dict[str, Any]:
    cand = state.candidates.get(candidate_id)
    if cand is None:
        raise NotFound(f"candidate {candidate_id} is not in the research state")
    hyps = [state.hypotheses[h] for h in cand.hypothesis_ids if h in state.hypotheses]
    exps = [state.experiments[e] for e in cand.experiment_ids if e in state.experiments]
    timeline: list[dict[str, Any]] = [
        {
            "iteration": c.iteration,
            "event_id": c.event_id,
            "type": "status_change",
            "from": c.previous_status,
            "to": c.new_status,
            "reason": c.reason,
            "triggered_by": c.triggered_by,
        }
        for c in cand.status_history
    ]
    timeline += [
        {
            "iteration": r["iteration"],
            "event_id": r["event_id"],
            "type": "ranked",
            "rank": r["rank"],
            "score": r["score"],
        }
        for r in cand.rank_history
    ]
    for h in hyps:
        timeline += [
            {
                "iteration": c.iteration,
                "event_id": c.event_id,
                "type": "hypothesis_status_change",
                "hypothesis_id": h.hypothesis_id,
                "from": c.previous_status,
                "to": c.new_status,
                "reason": c.reason,
                "triggered_by": c.triggered_by,
            }
            for c in h.status_history
            if c.previous_status is not None
        ]
    for e in exps:
        for rid in e.result_ids:
            r = state.results[rid]
            timeline.append(
                {
                    "iteration": r.iteration,
                    "event_id": r.event_id,
                    "type": "result",
                    "experiment_id": e.experiment_id,
                    "result_id": rid,
                    "evidence_type": r.evidence_type,
                    "summary": r.summary,
                }
            )
    timeline.sort(key=lambda t: (t["iteration"], t["event_id"]))
    return {
        "candidate": {
            k: getattr(cand, k)
            for k in (
                "candidate_id",
                "name",
                "origin",
                "bacteriocin_class",
                "validation_status",
                "status",
                "implicit",
                "rejection_reason",
            )
        },
        "status_history": [_dump(c) for c in cand.status_history],
        "rank_history": cand.rank_history,
        "hypotheses": [
            {
                "hypothesis_id": h.hypothesis_id,
                "statement": h.statement,
                "status": h.status,
                "contested": h.contested,
            }
            for h in hyps
        ],
        "experiments": [
            {
                "experiment_id": e.experiment_id,
                "status": e.status,
                "hypothesis_id": e.hypothesis_id,
                "result_ids": e.result_ids,
            }
            for e in exps
        ],
        "relationships": [
            _dump(r) for r in state.relationships.values() if r.candidate_id == candidate_id
        ],
        "timeline": timeline,
    }


def get_hypothesis_history(state: ResearchState, hypothesis_id: str) -> dict[str, Any]:
    hyp = state.hypotheses.get(hypothesis_id)
    if hyp is None:
        raise NotFound(f"hypothesis {hypothesis_id} is not in the research state")
    timeline: list[dict[str, Any]] = [
        {
            "iteration": c.iteration,
            "event_id": c.event_id,
            "type": "status_change",
            "from": c.previous_status,
            "to": c.new_status,
            "reason": c.reason,
            "evidence_strength": c.evidence_strength,
            "confidence": c.confidence,
            "triggered_by": c.triggered_by,
        }
        for c in hyp.status_history
    ]
    timeline += [
        {
            "iteration": o["iteration"],
            "event_id": o["event_id"],
            "type": "observation",
            "finding_id": o["finding_id"],
            "experiment_id": o["experiment_id"],
            "analysis_status": o["analysis_status"],
            "evidence_strength": o["evidence_strength"],
            "changed_status": (o["analysis_status"] == "inconclusive" and "untouched") or None,
        }
        for o in hyp.observations
    ]
    timeline.sort(key=lambda t: (t["iteration"], t["event_id"]))
    return {
        "hypothesis": {
            k: getattr(hyp, k)
            for k in (
                "hypothesis_id",
                "statement",
                "candidate_id",
                "falsified_if",
                "status",
                "contested",
                "n_supporting",
                "n_weakening",
                "n_inconclusive",
                "evidence_basis",
                "epistemic_status",
            )
        },
        "status_history": [_dump(c) for c in hyp.status_history],
        "observations": hyp.observations,
        "experiment_ids": hyp.experiment_ids,
        "evidence": [_dump(state.evidence[e]) for e in hyp.evidence_ids if e in state.evidence],
        "timeline": timeline,
    }


def get_experiment_history(
    state: ResearchState, *, candidate_id: str | None = None, hypothesis_id: str | None = None
) -> list[dict[str, Any]]:
    out = []
    for e in state.experiments.values():
        if candidate_id and e.candidate_id != candidate_id:
            continue
        if hypothesis_id and e.hypothesis_id != hypothesis_id:
            continue
        results = [state.results[r] for r in e.result_ids if r in state.results]
        findings = [
            state.findings[f] for r in results for f in r.finding_ids if f in state.findings
        ]
        out.append(
            {
                "experiment_id": e.experiment_id,
                "candidate_id": e.candidate_id,
                "hypothesis_id": e.hypothesis_id,
                "status": e.status,
                "planned_iteration": e.planned_iteration,
                "completed_iteration": e.completed_iteration,
                "implicit": e.implicit,
                "spec": e.spec,
                "results": [
                    {
                        "result_id": r.result_id,
                        "evidence_type": r.evidence_type,
                        "model_version": r.model_version,
                        "summary": r.summary,
                    }
                    for r in results
                ],
                "findings": [
                    {
                        "finding_id": f.finding_id,
                        "analysis_status": f.analysis_status,
                        "evidence_strength": f.evidence_strength,
                        "confidence": f.confidence,
                    }
                    for f in findings
                ],
            }
        )
    out.sort(key=lambda x: (x["planned_iteration"], x["experiment_id"]))
    return out


def get_open_questions(
    state: ResearchState, *, include_derived: bool = True
) -> list[dict[str, Any]]:
    """Stored open questions (from analyses) plus questions the current state itself implies."""
    out = [
        {
            "question_id": q.question_id,
            "kind": q.kind,
            "text": q.text,
            "opened_iteration": q.opened_iteration,
            "related_ids": q.related_ids,
            "derived": False,
        }
        for q in state.questions.values()
        if q.status == "open"
    ]
    if include_derived:
        for h in state.hypotheses.values():
            if h.status == "open" and not h.experiment_ids:
                out.append(
                    {
                        "question_id": f"derived:untested:{h.hypothesis_id}",
                        "kind": "untested_hypothesis",
                        "text": f"No experiment has tested hypothesis {h.hypothesis_id}: {h.statement or '(no statement)'}",
                        "opened_iteration": h.registered_iteration,
                        "related_ids": [f"hypothesis:{h.hypothesis_id}"],
                        "derived": True,
                    }
                )
            if h.contested:
                out.append(
                    {
                        "question_id": f"derived:contested:{h.hypothesis_id}",
                        "kind": "contested_hypothesis",
                        "text": f"Hypothesis {h.hypothesis_id} is contested: its two most recent decisive results disagree (now {h.status}).",
                        "opened_iteration": state.iteration,
                        "related_ids": [f"hypothesis:{h.hypothesis_id}"],
                        "derived": True,
                    }
                )
        for r in state.relationships.values():
            if r.relationship not in DECISIVE_RELATIONSHIPS and r.n_unresolved:
                out.append(
                    {
                        "question_id": f"derived:unresolved:{r.candidate_id}::{r.variable}",
                        "kind": "unresolved_relationship",
                        "text": f"The effect of {r.variable} on {r.candidate_id} is unresolved after {r.n_unresolved} controlled comparison(s).",
                        "opened_iteration": state.iteration,
                        "related_ids": [f"candidate:{r.candidate_id}"],
                        "derived": True,
                    }
                )
    out.sort(key=lambda q: (q["opened_iteration"], q["question_id"]))
    return out


def active_uncertainties(
    state: ResearchState, *, min_severity: str = "low"
) -> list[dict[str, Any]]:
    rank = {"low": 0, "medium": 1, "high": 2}
    items = [
        u
        for u in state.uncertainties.values()
        if u.status == "active" and rank.get(u.severity, 1) >= rank[min_severity]
    ]
    items.sort(key=lambda u: (-rank.get(u.severity, 1), u.uncertainty_id))
    return [
        {
            "uncertainty_id": u.uncertainty_id,
            "kind": u.kind,
            "severity": u.severity,
            "description": u.description,
            "affects": u.affects,
            "first_seen_iteration": u.first_seen_iteration,
            "last_seen_iteration": u.last_seen_iteration,
            "occurrences": u.occurrences,
        }
        for u in items
    ]


def get_relationships(
    state: ResearchState, candidate_id: str | None = None
) -> list[dict[str, Any]]:
    return [
        _dump(r) for r in state.relationships.values() if candidate_id in (None, r.candidate_id)
    ]


def summarize_current_state(
    state: ResearchState, *, top_candidates: int = 5, max_questions: int = 8
) -> dict[str, Any]:
    by_hyp = Counter(h.status for h in state.hypotheses.values())
    by_cand = Counter(c.status for c in state.candidates.values())
    by_type = Counter(r.evidence_type for r in state.results.values())
    latest = state.rankings[-1] if state.rankings else None
    versions = sorted(v.name for v in state.model_versions.values() if "result" in v.components)
    wet = by_type.get("wet-lab-derived", 0)
    questions = get_open_questions(state)
    return {
        "iteration": state.iteration,
        "event_count": state.event_count,
        "last_event_hash": state.last_event_hash,
        "objective": state.objective,
        "counts": {
            "candidates": dict(by_cand),
            "hypotheses": dict(by_hyp),
            "experiments": len(state.experiments),
            "results": len(state.results),
            "findings": len(state.findings),
            "evidence": len(state.evidence),
        },
        "provenance": (
            f"{len(state.results)} result(s): {dict(by_type) or 'none'}. "
            + (
                "Nothing here is experimentally validated."
                if not wet
                else f"{wet} wet-lab-derived result(s); the rest are not experimentally validated."
            )
        ),
        "hypotheses": [
            {
                "hypothesis_id": h.hypothesis_id,
                "status": h.status,
                "contested": h.contested,
                "statement": h.statement,
                "last_change": (h.status_history[-1].reason if len(h.status_history) > 1 else None),
                "n_supporting": h.n_supporting,
                "n_weakening": h.n_weakening,
                "n_inconclusive": h.n_inconclusive,
            }
            for h in state.hypotheses.values()
        ],
        "rejected_hypotheses": [
            {
                "hypothesis_id": h.hypothesis_id,
                "statement": h.statement,
                "reason": h.status_history[-1].reason,
                "iteration": h.status_history[-1].iteration,
                "triggered_by": h.status_history[-1].triggered_by,
            }
            for h in state.rejected_hypotheses
        ],
        "rejected_candidates": [
            {"candidate_id": c.candidate_id, "name": c.name, "reason": c.rejection_reason}
            for c in state.rejected_candidates
        ],
        "latest_ranking": None
        if latest is None
        else {"iteration": latest.iteration, "top": latest.ranking[:top_candidates]},
        "known_relationships": [
            {
                "candidate_id": r.candidate_id,
                "variable": r.variable,
                "relationship": r.relationship,
                "effect_size": r.effect_size,
                "n_confirming": r.n_confirming,
                "changes": max(0, len(r.history) - 1),
            }
            for r in state.relationships.values()
            if r.relationship
        ],
        "open_questions": questions[:max_questions],
        "n_open_questions": len(questions),
        "active_uncertainties": active_uncertainties(state, min_severity="medium")[:max_questions],
        "model_versions": versions,
        "model_version_warning": (
            f"results come from {len(versions)} different model versions; they may not be directly comparable"
            if len(versions) > 1
            else None
        ),
    }


__all__ = [
    "active_uncertainties",
    "get_candidate_history",
    "get_experiment_history",
    "get_hypothesis_history",
    "get_open_questions",
    "get_relationships",
    "summarize_current_state",
]
