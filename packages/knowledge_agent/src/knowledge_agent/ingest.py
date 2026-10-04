"""Turn the other agents' outputs into state events.

Each ``record_*`` / ``register_*`` function reads ``session.state``, decides what is new, and
emits events. It never edits state directly and never overwrites: a changed belief becomes a
*transition event* naming the previous value, so the history stays whole.

Input leniency: results arrive from deterministic agents (full envelopes) and from reasoning
sub-agents (looser JSON), so each parser accepts an envelope or its ``decision``, tolerates
compact forms, and says what it assumed in ``warnings`` rather than refusing.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from .errors import StateConflict, StateInputError
from .events import canonical
from .reducer import DECISIVE_RELATIONSHIPS, relationship_key
from .session import Session

#: analysis vocabulary -> the three values the state understands. Sub-agents may say
#: "contradicted" (the candidate agent's vocabulary) or "untouched" (the analysis guide's).
_ANALYSIS_STATUS = {
    "supported": "supported",
    "weakened": "weakened",
    "inconclusive": "inconclusive",
    "contradicted": "weakened",
    "refuted": "weakened",
    "untouched": "inconclusive",
    "open": "inconclusive",
}
_WET_LAB = "wet-lab-derived"


def _digest(*parts: Any, n: int = 16) -> str:
    return hashlib.sha256(canonical(list(parts)).encode()).hexdigest()[:n]


def normalise_text(text: str) -> str:
    """Case, whitespace and digits are noise when deciding two statements are the same."""
    return re.sub(r"\d+(?:\.\d+)?", "#", re.sub(r"\s+", " ", text.strip().lower()))


def question_id(kind: str, text: str, *scope: str) -> str:
    return f"q_{_digest(kind, normalise_text(text), *scope)}"


def uncertainty_id(kind: str, description: str) -> str:
    return f"unc_{_digest(kind, normalise_text(description))}"


def _decision(analysis_result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(analysis_result, dict):
        raise StateInputError(
            "analysis_result must be a JSON object (a Result Analysis envelope or its decision)"
        )
    decision = (
        analysis_result.get("decision")
        if isinstance(analysis_result.get("decision"), dict)
        else analysis_result
    )
    return decision


def _guard_validation(session: Session, claimed: str | None, label: str) -> str:
    """Nothing is experimentally validated without wet-lab-derived evidence in the state."""
    if claimed in (None, ""):
        return "unvalidated"
    if claimed == "experimentally-validated":
        has_wet_lab = any(r.evidence_type == _WET_LAB for r in session.state.results.values())
        if not has_wet_lab:
            session.warn(
                f"{label} claimed 'experimentally-validated' but no wet-lab-derived result exists; recorded as 'unvalidated'."
            )
            return "unvalidated"
    return claimed


# ---------------------------------------------------------------------------
# Objective
# ---------------------------------------------------------------------------


def set_objective(session: Session, objective: dict[str, Any]) -> None:
    if not isinstance(objective, dict) or not objective:
        raise StateInputError("objective must be a non-empty JSON object")
    if session.state.objective == objective:
        session.warn("objective unchanged; nothing recorded")
        return
    session.emit(
        "objective_set", objective=objective, previous_objective=session.state.objective or None
    )


# ---------------------------------------------------------------------------
# Candidates and hypotheses (from the candidate agent)
# ---------------------------------------------------------------------------


def _candidate_fields(c: dict[str, Any]) -> dict[str, Any]:
    features = c.get("features") if isinstance(c.get("features"), dict) else {}
    score = c.get("score") if isinstance(c.get("score"), dict) else {}
    return {
        "candidate_id": c.get("candidate_id"),
        "name": c.get("name"),
        "origin": c.get("origin"),
        "sequence": c.get("sequence"),
        "bacteriocin_class": c.get("bacteriocin_class") or features.get("bacteriocin_class"),
        "validation_status": c.get("validation_status"),
        "expected_failure_modes": list(c.get("expected_failure_modes") or []),
        "evidence_ids": list(c.get("evidence_ids") or []),
        "rank": c.get("rank"),
        "score": score.get("total", c.get("score_total")),
    }


def _hypotheses_of(c: dict[str, Any]) -> list[dict[str, Any]]:
    full = [
        h for h in (c.get("hypotheses") or []) if isinstance(h, dict) and h.get("hypothesis_id")
    ]
    if full:
        return full
    # Compact form (the candidate launcher's default reply): ids plus the primary hypothesis's text.
    ids = [h for h in (c.get("hypothesis_ids") or []) if h]
    out = []
    for i, hid in enumerate(ids):
        out.append(
            {
                "hypothesis_id": hid,
                "statement": c.get("hypothesis") if i == 0 else "",
                "falsified_if": c.get("falsified_if") if i == 0 else None,
                "predicted_inhibition_fraction": c.get("predicted_inhibition_fraction_PRIOR")
                if i == 0
                else None,
            }
        )
    return out


def register_candidates(session: Session, envelope: dict[str, Any]) -> None:
    """Record the candidate agent's proposals: new candidates, their hypotheses, and this ranking."""
    if not isinstance(envelope, dict):
        raise StateInputError("candidate output must be a JSON object")
    decision = envelope.get("decision") if isinstance(envelope.get("decision"), dict) else envelope
    candidates = [c for c in (decision.get("candidates") or []) if isinstance(c, dict)]
    if not candidates and not decision.get("rejected"):
        raise StateInputError(
            "no candidates found: expected decision.candidates (or candidates) from the candidate agent"
        )

    ranking: list[dict[str, Any]] = []
    for c in candidates:
        f = _candidate_fields(c)
        cid = f["candidate_id"]
        if not cid:
            session.warn("a candidate without candidate_id was skipped")
            continue
        if cid not in session.state.candidates:
            session.emit(
                "candidate_registered",
                triggered_by=[
                    f"candidate_run:{(envelope.get('artifacts') or {}).get('run_id', 'unknown')}"
                ],
                candidate_id=cid,
                name=f["name"],
                origin=f["origin"],
                sequence=f["sequence"],
                bacteriocin_class=f["bacteriocin_class"],
                validation_status=_guard_validation(
                    session, f["validation_status"], f"candidate {cid}"
                ),
                expected_failure_modes=f["expected_failure_modes"],
                evidence_ids=f["evidence_ids"],
                status="proposed",
            )
        for h in _hypotheses_of(c):
            if h["hypothesis_id"] not in session.state.hypotheses:
                session.emit(
                    "hypothesis_registered",
                    triggered_by=[f"candidate:{cid}"],
                    hypothesis_id=h["hypothesis_id"],
                    statement=h.get("statement", ""),
                    candidate_id=h.get("candidate_id") or cid,
                    falsified_if=h.get("falsified_if"),
                    predicted_inhibition_fraction=h.get("predicted_inhibition_fraction"),
                    evidence_ids=list(h.get("evidence_ids") or []),
                )
        if f["rank"] is not None:
            ranking.append({"candidate_id": cid, "rank": f["rank"], "score": f["score"]})

    for r in decision.get("rejected") or []:
        cid = r.get("candidate_id") if isinstance(r, dict) else None
        if not cid:
            session.warn(f"a filtered candidate without an id was not recorded ({str(r)[:80]})")
            continue
        if cid not in session.state.candidates:
            session.emit(
                "candidate_registered",
                candidate_id=cid,
                name=r.get("name"),
                status="rejected",
                rejection_reason=r.get("reason", "filtered by the candidate agent"),
                reason="filtered by the candidate agent",
            )

    if ranking:
        ranking.sort(key=lambda x: x["rank"])
        session.emit(
            "ranking_recorded",
            source=(envelope.get("artifacts") or {}).get("run_id") or "candidate_agent",
            ranking=ranking,
        )
    version = envelope.get("model_version")
    if version:
        session.emit("model_version_observed", name=version, component="candidate-agent")


def reject_candidate(
    session: Session, candidate_id: str, reason: str, triggered_by: list[str] | None = None
) -> None:
    cand = session.state.candidates.get(candidate_id)
    if cand is None:
        raise StateInputError(f"unknown candidate {candidate_id}")
    if cand.status == "rejected":
        session.warn(f"candidate {candidate_id} is already rejected; nothing recorded")
        return
    session.emit(
        "candidate_status_update",
        triggered_by=triggered_by or ["manual"],
        candidate_id=candidate_id,
        previous_status=cand.status,
        new_status="rejected",
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Experiment plans
# ---------------------------------------------------------------------------


def _specs_of(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [p for p in payload if isinstance(p, dict)]
    if isinstance(payload, dict):
        for key in ("specs", "experiment_specs"):
            if isinstance(payload.get(key), list):
                return [p for p in payload[key] if isinstance(p, dict)]
        decision = payload.get("decision")
        if isinstance(decision, dict) and isinstance(decision.get("specs"), list):
            return [p for p in decision["specs"] if isinstance(p, dict)]
        return [payload]
    raise StateInputError(
        "experiment plan must be an ExperimentSpec, a list of them, or an object with 'specs'"
    )


def record_experiment_plan(session: Session, payload: Any) -> None:
    specs = _specs_of(payload)
    if not specs:
        raise StateInputError("no ExperimentSpec found in the plan")
    for spec in specs:
        eid = spec.get("experiment_id")
        if not eid:
            raise StateInputError("every ExperimentSpec needs an experiment_id")
        existing = session.state.experiments.get(eid)
        if existing is not None:
            if existing.spec == spec:
                session.warn(
                    f"experiment {eid} already planned with an identical spec; nothing recorded"
                )
                continue
            if existing.spec is None:
                session.warn(
                    f"experiment {eid} was recorded implicitly without a spec; the supplied spec cannot be attached without rewriting history"
                )
                continue
            raise StateConflict(
                f"experiment {eid} already exists with a different spec; plan a new experiment_id instead of overwriting"
            )
        cid, hid = spec.get("candidate_id"), spec.get("hypothesis_id")
        if cid and cid not in session.state.candidates:
            session.warn(f"experiment {eid} names unregistered candidate {cid}")
        if hid and hid not in session.state.hypotheses:
            session.warn(f"experiment {eid} names unregistered hypothesis {hid}")
        session.emit(
            "experiment_planned",
            triggered_by=[f"hypothesis:{hid}"] if hid else [],
            experiment_id=eid,
            candidate_id=cid,
            hypothesis_id=hid,
            spec=spec,
        )


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


def register_evidence(session: Session, evidence: list[dict[str, Any]]) -> int:
    """Record evidence items (contract ``Evidence`` shape). Returns how many were new."""
    if not isinstance(evidence, list):
        raise StateInputError("evidence must be a list of Evidence objects")
    new = 0
    for item in evidence:
        if not isinstance(item, dict) or not item.get("evidence_id"):
            session.warn("an evidence item without evidence_id was skipped")
            continue
        evid = item["evidence_id"]
        if evid in session.state.evidence:
            continue  # content-addressed: the same id is the same claim
        session.emit(
            "evidence_recorded",
            evidence_id=evid,
            evidence_type=item.get("evidence_type", "unknown"),
            claim=item.get("claim", ""),
            source=item.get("source"),
            confidence=item.get("confidence"),
            subject_ids=list(item.get("subject_ids") or []),
            derived_from_evidence_type=item.get("derived_from_evidence_type"),
            record=item,
        )
        new += 1
    return new


# ---------------------------------------------------------------------------
# Questions and uncertainties
# ---------------------------------------------------------------------------


def _open_question(
    session: Session,
    kind: str,
    text: str,
    *,
    related: list[str],
    triggered_by: list[str],
    params: dict[str, Any] | None = None,
    scope: tuple[str, ...] = (),
) -> None:
    qid = question_id(kind, text, *scope)
    existing = session.state.questions.get(qid)
    if existing is not None and existing.status == "open":
        return
    session.emit(
        "question_opened",
        triggered_by=triggered_by,
        question_id=qid,
        text=text,
        kind=kind,
        related_ids=related,
        params=params or {},
        reason="reopened" if existing else "opened",
    )


def close_question(
    session: Session, question_id_: str, reason: str, triggered_by: list[str] | None = None
) -> None:
    q = session.state.questions.get(question_id_)
    if q is None:
        raise StateInputError(f"unknown question {question_id_}")
    if q.status != "open":
        session.warn(f"question {question_id_} is already closed; nothing recorded")
        return
    session.emit(
        "question_closed",
        triggered_by=triggered_by or ["manual"],
        question_id=question_id_,
        reason=reason,
    )


def _sync_uncertainties(
    session: Session, uncertainties: list[Any], scope: str, triggered_by: list[str]
) -> None:
    """Observe what this analysis reports; resolve what the same scope reported before and no longer does."""
    current: dict[str, dict[str, Any]] = {}
    for u in uncertainties:
        if isinstance(u, str):
            u = {"kind": "epistemic", "severity": "medium", "description": u, "affects": []}
        if not isinstance(u, dict) or not u.get("description"):
            continue
        current[uncertainty_id(u.get("kind", "epistemic"), u["description"])] = u
    for uid, u in current.items():
        session.emit(
            "uncertainty_observed",
            triggered_by=triggered_by,
            uncertainty_id=uid,
            kind=u.get("kind", "epistemic"),
            severity=u.get("severity", "medium"),
            description=u["description"],
            affects=list(u.get("affects") or []),
            scope=scope,
        )
    for uid, rec in list(session.state.uncertainties.items()):
        if rec.status == "active" and rec.scope == scope and uid not in current:
            session.emit(
                "uncertainty_resolved",
                triggered_by=triggered_by,
                uncertainty_id=uid,
                reason="no longer reported by the latest analysis of the same scope",
            )


# ---------------------------------------------------------------------------
# The analysis: the main operation
# ---------------------------------------------------------------------------


def _decide_hypothesis_status(
    session: Session, hyp, analysis_status: str, strength: str | None
) -> tuple[str, str] | None:
    """(new_status, reason) or None when the hypothesis is left untouched. ``hyp`` already includes this observation."""
    if analysis_status == "inconclusive":
        return None
    policy = session.policy
    if analysis_status == "supported":
        if hyp.status == "supported":
            return None
        why = "supported by a new result" + (
            " after having been rejected (reopened)" if hyp.status == "rejected" else ""
        )
        return "supported", f"{why} ({strength or 'unrated'} evidence)"
    # weakened
    decisive = [o for o in hyp.observations if o["analysis_status"] != "inconclusive"]
    consecutive = 0
    for o in reversed(decisive):
        if o["analysis_status"] != "weakened":
            break
        consecutive += 1
    if policy.reject_on_strong_weakening and strength == "strong":
        new, why = "rejected", "weakened by strong evidence"
    elif consecutive >= policy.reject_after_consecutive_weakened:
        new, why = "rejected", f"weakened by {consecutive} consecutive decisive results"
    else:
        new, why = "weakened", f"weakened by {strength or 'unrated'} evidence"
    return None if new == hyp.status else (new, why)


def _ensure_context(
    session: Session,
    d: dict[str, Any],
    result: dict[str, Any] | None,
    spec: dict[str, Any] | None,
    hypothesis: dict[str, Any] | None,
    candidate: dict[str, Any] | None,
) -> tuple[str, str | None, str]:
    eid, rid = d.get("experiment_id"), d.get("result_id")
    cid = (
        d.get("candidate_id")
        or (result or {}).get("candidate_id")
        or (spec or {}).get("candidate_id")
    )
    hid = (
        d.get("hypothesis_id")
        or (hypothesis or {}).get("hypothesis_id")
        or (spec or {}).get("hypothesis_id")
    )
    if not (eid and rid and cid):
        raise StateInputError(
            "analysis needs experiment_id, result_id and candidate_id (in the analysis, or in result/spec)"
        )
    if cid not in session.state.candidates:
        session.warn(f"candidate {cid} was not registered; created implicitly")
        c = candidate or {}
        session.emit(
            "candidate_registered",
            candidate_id=cid,
            name=c.get("name"),
            origin=c.get("origin"),
            sequence=c.get("sequence"),
            status="proposed",
            implicit=True,
            reason="created implicitly from an analysis",
        )
    if hid and hid not in session.state.hypotheses:
        session.warn(f"hypothesis {hid} was not registered; created implicitly")
        h = hypothesis or {}
        session.emit(
            "hypothesis_registered",
            hypothesis_id=hid,
            statement=h.get("statement", ""),
            candidate_id=h.get("candidate_id") or cid,
            falsified_if=h.get("falsified_if"),
            predicted_inhibition_fraction=h.get("predicted_inhibition_fraction"),
            implicit=True,
            reason="created implicitly from an analysis",
        )
    if eid not in session.state.experiments:
        if spec is None:
            session.warn(
                f"experiment {eid} was never planned and no spec was supplied; recorded implicitly without a spec"
            )
        session.emit(
            "experiment_planned",
            experiment_id=eid,
            candidate_id=cid,
            hypothesis_id=hid,
            spec=spec,
            implicit=True,
        )
    return eid, hid, cid


def record_analysis(
    session: Session,
    analysis_result: dict[str, Any],
    *,
    result: dict[str, Any] | None = None,
    spec: dict[str, Any] | None = None,
    hypothesis: dict[str, Any] | None = None,
    candidate: dict[str, Any] | None = None,
    evidence: list[dict[str, Any]] | None = None,
    advance_iteration: bool = True,
) -> None:
    d = _decision(analysis_result)
    envelope = analysis_result if isinstance(analysis_result.get("decision"), dict) else {}
    artifacts = envelope.get("artifacts") or {}

    # A failed attempt has no measurement: it is a failed attempt, never a negative finding.
    if artifacts.get("failed_attempt"):
        eid = d.get("experiment_id") or (spec or {}).get("experiment_id")
        if not eid:
            raise StateInputError("failed attempt without an experiment_id")
        if eid not in session.state.experiments:
            session.emit(
                "experiment_planned",
                experiment_id=eid,
                candidate_id=d.get("candidate_id"),
                hypothesis_id=d.get("hypothesis_id"),
                spec=spec,
                implicit=True,
            )
        session.emit(
            "experiment_failed",
            triggered_by=[f"experiment:{eid}"],
            experiment_id=eid,
            reason=d.get("status_basis", "failed attempt"),
        )
        _open_question(
            session,
            "failed_experiment",
            f"Why did experiment {eid} fail, and can it be repaired and re-run?",
            related=[f"experiment:{eid}"],
            triggered_by=[f"experiment:{eid}"],
            scope=(eid,),
        )
        if advance_iteration:
            session.emit("iteration_advanced", to=session.state.iteration + 1)
        return

    raw_status = d.get("hypothesis_status")
    if raw_status not in _ANALYSIS_STATUS:
        raise StateInputError(
            f"analysis hypothesis_status must be one of {sorted(_ANALYSIS_STATUS)}, got {raw_status!r}"
        )
    status = _ANALYSIS_STATUS[raw_status]
    if raw_status != status:
        session.warn(f"analysis status {raw_status!r} was read as {status!r}")

    # Idempotence first: re-submitting an analysis already in the state must change nothing at all
    # (no events, no counters, no iteration), so a retried tool call is harmless.
    early_hid = (
        d.get("hypothesis_id")
        or (hypothesis or {}).get("hypothesis_id")
        or (spec or {}).get("hypothesis_id")
    )
    early_fid = (
        d.get("finding_id")
        or f"find_{_digest(d.get('experiment_id'), d.get('result_id'), early_hid, status)}"
    )
    if early_fid in session.state.findings:
        session.warn(f"finding {early_fid} was already recorded; nothing changed")
        return

    eid, hid, cid = _ensure_context(session, d, result, spec, hypothesis, candidate)
    rid = d["result_id"]
    refs = [f"experiment:{eid}", f"result:{rid}"]

    # Evidence the analysis emitted (and any supplied alongside it).
    items = list(envelope.get("evidence") or []) + list(evidence or [])
    register_evidence(session, items)
    evidence_ids = [i["evidence_id"] for i in items if isinstance(i, dict) and i.get("evidence_id")]

    # The result itself.
    if rid not in session.state.results:
        observed = d.get("observed") or {}
        supplied = result is not None
        if not supplied:
            session.warn(
                f"result {rid} was not supplied; only the analysis's observed summary was recorded"
            )
        session.emit(
            "result_recorded",
            triggered_by=[f"experiment:{eid}"],
            result_id=rid,
            experiment_id=eid,
            candidate_id=cid,
            evidence_type=(result or {}).get("evidence_type")
            or d.get("source_evidence_type", "simulation-derived"),
            model_version=(result or {}).get("model_version"),
            result=result or {},
            summary=observed or _summary_of(result),
            result_supplied=supplied,
        )
    versions = {
        (result or {}).get("model_version"): "result",
        envelope.get("model_version"): "analysis",
        d.get("model_version"): "analysis",
    }
    for name, component in versions.items():
        if name:
            session.emit("model_version_observed", name=name, component=component)

    fid = early_fid
    refs.append(f"finding:{fid}")
    strength, confidence = (
        d.get("evidence_strength"),
        d.get("confidence", envelope.get("confidence")),
    )
    session.emit(
        "finding_recorded",
        triggered_by=refs,
        finding_id=fid,
        experiment_id=eid,
        result_id=rid,
        candidate_id=cid,
        hypothesis_id=hid,
        analysis_status=status,
        evidence_strength=strength,
        confidence=confidence,
        status_basis=d.get("status_basis", ""),
        findings=d.get("findings") or [],
        unexpected_results=d.get("unexpected_results") or [],
        drivers=d.get("drivers") or [],
        evidence_ids=evidence_ids,
        source_evidence_type=d.get("source_evidence_type", "simulation-derived"),
        analysis_model_version=d.get("model_version") or envelope.get("model_version"),
    )

    _transition_hypothesis(session, hid, cid, status, strength, confidence, refs)
    cand = session.state.candidates[cid]
    if cand.status == "proposed":
        session.emit(
            "candidate_status_update",
            triggered_by=refs,
            candidate_id=cid,
            previous_status="proposed",
            new_status="under_test",
            reason=f"first result recorded ({rid})",
        )
    _record_relationships(session, cid, d.get("findings") or [], fid, refs)
    _record_questions(session, d, envelope, cid, hid, refs)
    _sync_uncertainties(session, list(d.get("uncertainties") or []), f"{cid}|{hid or ''}", refs)
    if advance_iteration:
        session.emit("iteration_advanced", to=session.state.iteration + 1)


def _summary_of(result: dict[str, Any] | None) -> dict[str, Any]:
    m = (result or {}).get("measurement") or {}
    return {
        k: m.get(k)
        for k in (
            "predicted_inhibition_fraction",
            "predicted_survival_fraction",
            "predicted_activity",
            "uncertainty",
        )
        if k in m
    }


def _transition_hypothesis(
    session: Session,
    hid: str | None,
    cid: str,
    status: str,
    strength: str | None,
    confidence: float | None,
    refs: list[str],
) -> None:
    if not hid:
        return
    hyp = session.state.hypotheses[hid]
    decided = _decide_hypothesis_status(session, hyp, status, strength)
    if decided is None:
        return
    new, why = decided
    previous = hyp.status
    session.emit(
        "hypothesis_update",
        triggered_by=refs,
        hypothesis_id=hid,
        previous_status=previous,
        new_status=new,
        evidence_strength=strength,
        confidence=confidence,
        reason=why,
    )
    _update_candidate_after_hypothesis(session, cid, hid, previous, new, refs)


def _update_candidate_after_hypothesis(
    session: Session, cid: str, hid: str, previous: str, new: str, refs: list[str]
) -> None:
    cand = session.state.candidates[cid]
    siblings = [
        session.state.hypotheses[h] for h in cand.hypothesis_ids if h in session.state.hypotheses
    ]
    if (
        new == "rejected"
        and session.policy.reject_candidate_when_all_hypotheses_rejected
        and siblings
        and all(h.status == "rejected" for h in siblings)
        and cand.status != "rejected"
    ):
        session.emit(
            "candidate_status_update",
            triggered_by=[f"hypothesis:{hid}", *refs],
            candidate_id=cid,
            previous_status=cand.status,
            new_status="rejected",
            reason=f"all {len(siblings)} of its hypotheses are rejected",
        )
    elif previous == "rejected" and cand.status == "rejected" and cand.experiment_ids:
        session.emit(
            "candidate_status_update",
            triggered_by=[f"hypothesis:{hid}", *refs],
            candidate_id=cid,
            previous_status="rejected",
            new_status="under_test",
            reason=f"hypothesis {hid} was reopened",
        )


def _record_relationships(
    session: Session, cid: str, findings: list[dict[str, Any]], fid: str, refs: list[str]
) -> None:
    for f in findings:
        if not isinstance(f, dict) or not f.get("controlled") or not f.get("variable"):
            continue  # only a controlled comparison can attribute a change to a variable
        var, rel = f["variable"], f.get("relationship", "unresolved")
        key = relationship_key(cid, var)
        previous = (
            session.state.relationships[key].relationship
            if key in session.state.relationships
            else None
        )
        session.emit(
            "relationship_observed",
            triggered_by=refs,
            candidate_id=cid,
            variable=var,
            relationship=rel,
            previous_relationship=previous,
            effect_size=f.get("effect_size"),
            finding_id=fid,
            reason=f.get("interpretation", ""),
        )
        if rel in DECISIVE_RELATIONSHIPS:
            if previous is not None and previous != rel:
                _open_question(
                    session,
                    "relationship_reversal",
                    f"The {var} relationship for {cid} changed from {previous} to {rel}; which result is right?",
                    related=[f"candidate:{cid}", f"finding:{fid}"],
                    triggered_by=refs,
                    scope=(cid, var),
                )
            for qid, q in list(session.state.questions.items()):
                if (
                    q.status == "open"
                    and q.kind == "resolve_variable"
                    and q.params.get("candidate_id") == cid
                    and q.params.get("variable") == var
                ):
                    session.emit(
                        "question_closed",
                        triggered_by=refs,
                        question_id=qid,
                        reason=f"a controlled comparison now gives a {rel} {var} relationship",
                    )


def _record_questions(
    session: Session,
    d: dict[str, Any],
    envelope: dict[str, Any],
    cid: str,
    hid: str | None,
    refs: list[str],
) -> None:
    related = [f"candidate:{cid}"] + ([f"hypothesis:{hid}"] if hid else [])
    for text in d.get("recommended_followup_questions") or []:
        if isinstance(text, str) and text.strip():
            _open_question(
                session, "followup", text, related=related, triggered_by=refs, scope=(cid,)
            )
    for u in d.get("unexpected_results") or []:
        if isinstance(u, dict) and u.get("description"):
            _open_question(
                session,
                "unexpected_result",
                f"Unexpected ({u.get('kind', 'result')}): {u['description']}",
                related=related + list(u.get("refs") or []),
                triggered_by=refs,
                scope=(cid,),
            )
    hints = (envelope.get("artifacts") or {}).get("planner_hints") or {}
    for s in hints.get("suggested_experiments") or []:
        if isinstance(s, dict) and s.get("vary"):
            key = relationship_key(cid, s["vary"])
            rec = session.state.relationships.get(key)
            if rec is not None and rec.relationship in DECISIVE_RELATIONSHIPS:
                continue  # already settled by a controlled comparison
            _open_question(
                session,
                "resolve_variable",
                f"Isolate the effect of {s['vary']} on {cid} (vary it alone; {s.get('reason', 'no controlled comparison exists')}).",
                related=related,
                triggered_by=refs,
                params={
                    "candidate_id": cid,
                    "variable": s["vary"],
                    "suggested_values": s.get("suggested_values"),
                },
                scope=(cid, s["vary"]),
            )


__all__ = [
    "close_question",
    "normalise_text",
    "question_id",
    "record_analysis",
    "record_experiment_plan",
    "register_candidates",
    "register_evidence",
    "reject_candidate",
    "set_objective",
    "uncertainty_id",
]
