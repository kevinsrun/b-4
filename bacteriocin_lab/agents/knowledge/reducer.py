"""The reducer: ``ResearchState`` as a pure projection of the event log.

Each handler *validates* its event against the current state before applying it. A
``hypothesis_update`` whose ``previous_status`` is not the hypothesis's actual status,
a result for an experiment that was never planned, a re-registered candidate: all are
rejected rather than absorbed, because accepting them would mean history had been
rewritten somewhere upstream. Nothing here reads a clock or generates an ID; replaying
the same events always yields the same state.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from bacteriocin_lab.shared import (
    CandidateRecord,
    EvidenceEntry,
    ExperimentRecord,
    FindingRecord,
    HypothesisRecord,
    ModelVersionRecord,
    ObjectiveRevision,
    QuestionRecord,
    RankingSnapshot,
    RelationshipRecord,
    ResearchState,
    ResultRecord,
    StateEvent,
    StatusChange,
    UncertaintyRecord,
)

from .errors import StateIntegrityError
from .events import hash_event

#: Relationship values that count as a decisive answer about a variable.
DECISIVE_RELATIONSHIPS = frozenset({"positive", "negative", "none", "non_monotonic"})


def relationship_key(candidate_id: str, variable: str) -> str:
    return f"{candidate_id}::{variable}"


def _change(ev: StateEvent, previous: str | None, new: str, **kw: Any) -> StatusChange:
    return StatusChange(
        event_id=ev.event_id,
        iteration=ev.iteration,
        timestamp=ev.timestamp,
        previous_status=previous,
        new_status=new,
        triggered_by=list(ev.triggered_by),
        **kw,
    )


def _get(ev: StateEvent, name: str, default: Any = None) -> Any:
    return (ev.model_extra or {}).get(name, default)


def _need(ev: StateEvent, *names: str) -> list[Any]:
    missing = [n for n in names if n not in (ev.model_extra or {})]
    if missing:
        raise StateIntegrityError(
            f"{ev.event_id} ({ev.event}) is missing required field(s): {', '.join(missing)}"
        )
    return [_get(ev, n) for n in names]


def _append_unique(items: list[str], value: str | None) -> None:
    if value and value not in items:
        items.append(value)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _objective_set(s: ResearchState, ev: StateEvent) -> None:
    (objective,) = _need(ev, "objective")
    s.objective_history.append(
        ObjectiveRevision(event_id=ev.event_id, iteration=ev.iteration, objective=objective)
    )
    s.objective = objective


def _iteration_advanced(s: ResearchState, ev: StateEvent) -> None:
    (to,) = _need(ev, "to")
    if to != s.iteration + 1:
        raise StateIntegrityError(
            f"{ev.event_id}: iteration cannot jump from {s.iteration} to {to}"
        )
    s.iteration = to


def _candidate_registered(s: ResearchState, ev: StateEvent) -> None:
    (cid,) = _need(ev, "candidate_id")
    if cid in s.candidates:
        raise StateIntegrityError(
            f"{ev.event_id}: candidate {cid} is already registered (registering twice would overwrite its history)"
        )
    status = _get(ev, "status", "proposed")
    rec = CandidateRecord(
        candidate_id=cid,
        name=_get(ev, "name"),
        origin=_get(ev, "origin"),
        sequence=_get(ev, "sequence"),
        bacteriocin_class=_get(ev, "bacteriocin_class"),
        validation_status=_get(ev, "validation_status", "unvalidated"),
        status=status,
        expected_failure_modes=list(_get(ev, "expected_failure_modes", [])),
        evidence_ids=list(_get(ev, "evidence_ids", [])),
        registered_event_id=ev.event_id,
        registered_iteration=ev.iteration,
        implicit=bool(_get(ev, "implicit", False)),
        rejection_reason=_get(ev, "rejection_reason"),
    )
    rec.status_history.append(_change(ev, None, status, reason=_get(ev, "reason", "registered")))
    s.candidates[cid] = rec


def _ranking_recorded(s: ResearchState, ev: StateEvent) -> None:
    (ranking,) = _need(ev, "ranking")
    for item in ranking:
        cand = s.candidates.get(item.get("candidate_id"))
        if cand is None:
            raise StateIntegrityError(
                f"{ev.event_id}: ranking names unregistered candidate {item.get('candidate_id')!r}"
            )
        cand.rank_history.append(
            {
                "iteration": ev.iteration,
                "rank": item.get("rank"),
                "score": item.get("score"),
                "event_id": ev.event_id,
            }
        )
    s.rankings.append(
        RankingSnapshot(
            event_id=ev.event_id,
            iteration=ev.iteration,
            source=_get(ev, "source", ""),
            ranking=list(ranking),
        )
    )


def _candidate_status_update(s: ResearchState, ev: StateEvent) -> None:
    cid, previous, new = _need(ev, "candidate_id", "previous_status", "new_status")
    cand = s.candidates.get(cid)
    if cand is None:
        raise StateIntegrityError(f"{ev.event_id}: unknown candidate {cid}")
    if cand.status != previous:
        raise StateIntegrityError(
            f"{ev.event_id}: candidate {cid} is {cand.status!r}, not {previous!r}; history is inconsistent"
        )
    cand.status = new
    cand.status_history.append(_change(ev, previous, new, reason=_get(ev, "reason", "")))
    cand.rejection_reason = _get(ev, "reason") if new == "rejected" else None


def _hypothesis_registered(s: ResearchState, ev: StateEvent) -> None:
    (hid,) = _need(ev, "hypothesis_id")
    if hid in s.hypotheses:
        raise StateIntegrityError(f"{ev.event_id}: hypothesis {hid} is already registered")
    cid = _get(ev, "candidate_id")
    rec = HypothesisRecord(
        hypothesis_id=hid,
        statement=_get(ev, "statement", ""),
        candidate_id=cid,
        falsified_if=_get(ev, "falsified_if"),
        predicted_inhibition_fraction=_get(ev, "predicted_inhibition_fraction"),
        evidence_ids=list(_get(ev, "evidence_ids", [])),
        registered_event_id=ev.event_id,
        registered_iteration=ev.iteration,
        implicit=bool(_get(ev, "implicit", False)),
    )
    rec.status_history.append(_change(ev, None, "open", reason=_get(ev, "reason", "registered")))
    s.hypotheses[hid] = rec
    if cid in s.candidates:
        _append_unique(s.candidates[cid].hypothesis_ids, hid)


def _hypothesis_update(s: ResearchState, ev: StateEvent) -> None:
    hid, previous, new = _need(ev, "hypothesis_id", "previous_status", "new_status")
    hyp = s.hypotheses.get(hid)
    if hyp is None:
        raise StateIntegrityError(f"{ev.event_id}: unknown hypothesis {hid}")
    if hyp.status != previous:
        raise StateIntegrityError(
            f"{ev.event_id}: hypothesis {hid} is {hyp.status!r}, not {previous!r}; history is inconsistent"
        )
    hyp.status = new
    hyp.status_history.append(
        _change(
            ev,
            previous,
            new,
            reason=_get(ev, "reason", ""),
            evidence_strength=_get(ev, "evidence_strength"),
            confidence=_get(ev, "confidence"),
        )
    )


def _experiment_planned(s: ResearchState, ev: StateEvent) -> None:
    (eid,) = _need(ev, "experiment_id")
    if eid in s.experiments:
        raise StateIntegrityError(f"{ev.event_id}: experiment {eid} is already recorded")
    cid, hid = _get(ev, "candidate_id"), _get(ev, "hypothesis_id")
    s.experiments[eid] = ExperimentRecord(
        experiment_id=eid,
        candidate_id=cid,
        hypothesis_id=hid,
        spec=_get(ev, "spec"),
        planned_iteration=ev.iteration,
        planned_event_id=ev.event_id,
        implicit=bool(_get(ev, "implicit", False)),
    )
    if cid in s.candidates:
        _append_unique(s.candidates[cid].experiment_ids, eid)
    if hid in s.hypotheses:
        _append_unique(s.hypotheses[hid].experiment_ids, eid)


def _experiment_failed(s: ResearchState, ev: StateEvent) -> None:
    (eid,) = _need(ev, "experiment_id")
    exp = s.experiments.get(eid)
    if exp is None:
        raise StateIntegrityError(f"{ev.event_id}: unknown experiment {eid}")
    exp.status = "failed"
    exp.completed_iteration = ev.iteration


def _result_recorded(s: ResearchState, ev: StateEvent) -> None:
    rid, eid = _need(ev, "result_id", "experiment_id")
    if rid in s.results:
        raise StateIntegrityError(f"{ev.event_id}: result {rid} is already recorded")
    exp = s.experiments.get(eid)
    if exp is None:
        raise StateIntegrityError(f"{ev.event_id}: result {rid} is for unrecorded experiment {eid}")
    etype = _get(ev, "evidence_type", "simulation-derived")
    s.results[rid] = ResultRecord(
        result_id=rid,
        experiment_id=eid,
        candidate_id=_get(ev, "candidate_id") or exp.candidate_id,
        evidence_type=etype,
        model_version=_get(ev, "model_version"),
        result=_get(ev, "result", {}),
        summary=_get(ev, "summary", {}),
        iteration=ev.iteration,
        event_id=ev.event_id,
        result_supplied=bool(_get(ev, "result_supplied", True)),
    )
    _append_unique(exp.result_ids, rid)
    exp.status = "completed"
    exp.completed_iteration = ev.iteration
    hyp = s.hypotheses.get(exp.hypothesis_id or "")
    if hyp is not None:
        hyp.evidence_basis[etype] = hyp.evidence_basis.get(etype, 0) + 1


def _finding_recorded(s: ResearchState, ev: StateEvent) -> None:
    fid, eid, rid = _need(ev, "finding_id", "experiment_id", "result_id")
    if fid in s.findings:
        raise StateIntegrityError(f"{ev.event_id}: finding {fid} is already recorded")
    if rid not in s.results:
        raise StateIntegrityError(f"{ev.event_id}: finding {fid} refers to unrecorded result {rid}")
    status = _get(ev, "analysis_status", "inconclusive")
    hid = _get(ev, "hypothesis_id")
    s.findings[fid] = FindingRecord(
        finding_id=fid,
        experiment_id=eid,
        result_id=rid,
        candidate_id=_get(ev, "candidate_id"),
        hypothesis_id=hid,
        analysis_status=status,
        evidence_strength=_get(ev, "evidence_strength"),
        confidence=_get(ev, "confidence"),
        status_basis=_get(ev, "status_basis", ""),
        findings=list(_get(ev, "findings", [])),
        unexpected_results=list(_get(ev, "unexpected_results", [])),
        drivers=list(_get(ev, "drivers", [])),
        evidence_ids=list(_get(ev, "evidence_ids", [])),
        source_evidence_type=_get(ev, "source_evidence_type", "simulation-derived"),
        analysis_model_version=_get(ev, "analysis_model_version"),
        iteration=ev.iteration,
        event_id=ev.event_id,
    )
    _append_unique(s.results[rid].finding_ids, fid)
    hyp = s.hypotheses.get(hid or "")
    if hyp is None:
        return
    previous_decisive = next(
        (
            o["analysis_status"]
            for o in reversed(hyp.observations)
            if o["analysis_status"] != "inconclusive"
        ),
        None,
    )
    hyp.observations.append(
        {
            "finding_id": fid,
            "experiment_id": eid,
            "result_id": rid,
            "analysis_status": status,
            "evidence_strength": _get(ev, "evidence_strength"),
            "confidence": _get(ev, "confidence"),
            "iteration": ev.iteration,
            "event_id": ev.event_id,
        }
    )
    if status == "supported":
        hyp.n_supporting += 1
    elif status == "weakened":
        hyp.n_weakening += 1
    else:
        hyp.n_inconclusive += 1
    if status != "inconclusive":
        # Contested = the most recent two decisive results disagree; agreement settles it again.
        hyp.contested = previous_decisive is not None and previous_decisive != status
    for evid in _get(ev, "evidence_ids", []):
        _append_unique(hyp.evidence_ids, evid)


def _relationship_observed(s: ResearchState, ev: StateEvent) -> None:
    cid, var, rel, previous = _need(
        ev, "candidate_id", "variable", "relationship", "previous_relationship"
    )
    key = relationship_key(cid, var)
    rec = s.relationships.get(key) or RelationshipRecord(candidate_id=cid, variable=var)
    if rec.relationship != previous:
        raise StateIntegrityError(
            f"{ev.event_id}: {key} is {rec.relationship!r}, not {previous!r}; history is inconsistent"
        )
    fid = _get(ev, "finding_id")
    _append_unique(rec.finding_ids, fid)
    if rel in DECISIVE_RELATIONSHIPS:
        if rel != rec.relationship:
            rec.history.append(
                _change(ev, rec.relationship, rel, reason=_get(ev, "reason", ""), confidence=None)
            )
            rec.relationship = rel
            rec.n_confirming = 1
        else:
            rec.n_confirming += 1
        rec.effect_size = _get(ev, "effect_size", rec.effect_size)
    else:
        rec.n_unresolved += 1
    s.relationships[key] = rec


def _evidence_recorded(s: ResearchState, ev: StateEvent) -> None:
    (evid,) = _need(ev, "evidence_id")
    if evid in s.evidence:
        raise StateIntegrityError(f"{ev.event_id}: evidence {evid} is already recorded")
    s.evidence[evid] = EvidenceEntry(
        evidence_id=evid,
        evidence_type=_get(ev, "evidence_type", "unknown"),
        claim=_get(ev, "claim", ""),
        source=_get(ev, "source"),
        confidence=_get(ev, "confidence"),
        subject_ids=list(_get(ev, "subject_ids", [])),
        derived_from_evidence_type=_get(ev, "derived_from_evidence_type"),
        first_seen_iteration=ev.iteration,
        event_id=ev.event_id,
        record=_get(ev, "record", {}),
    )


def _question_opened(s: ResearchState, ev: StateEvent) -> None:
    (qid,) = _need(ev, "question_id")
    existing = s.questions.get(qid)
    if existing is not None:
        if existing.status == "open":
            raise StateIntegrityError(f"{ev.event_id}: question {qid} is already open")
        existing.status, existing.closed_iteration, existing.close_reason = "open", None, None
        existing.history.append(
            _change(ev, "closed", "open", reason=_get(ev, "reason", "reopened"))
        )
        return
    rec = QuestionRecord(
        question_id=qid,
        text=_get(ev, "text", ""),
        kind=_get(ev, "kind", "followup"),
        related_ids=list(_get(ev, "related_ids", [])),
        params=_get(ev, "params", {}),
        opened_iteration=ev.iteration,
        opened_by=list(ev.triggered_by),
    )
    rec.history.append(_change(ev, None, "open"))
    s.questions[qid] = rec


def _question_closed(s: ResearchState, ev: StateEvent) -> None:
    (qid,) = _need(ev, "question_id")
    q = s.questions.get(qid)
    if q is None or q.status != "open":
        raise StateIntegrityError(f"{ev.event_id}: question {qid} is not open")
    q.status, q.closed_iteration, q.closed_by, q.close_reason = (
        "closed",
        ev.iteration,
        list(ev.triggered_by),
        _get(ev, "reason"),
    )
    q.history.append(_change(ev, "open", "closed", reason=_get(ev, "reason", "")))


def _uncertainty_observed(s: ResearchState, ev: StateEvent) -> None:
    (uid,) = _need(ev, "uncertainty_id")
    u = s.uncertainties.get(uid)
    if u is None:
        u = UncertaintyRecord(
            uncertainty_id=uid,
            kind=_get(ev, "kind", "epistemic"),
            severity=_get(ev, "severity", "medium"),
            description=_get(ev, "description", ""),
            affects=list(_get(ev, "affects", [])),
            scope=_get(ev, "scope", ""),
            first_seen_iteration=ev.iteration,
            last_seen_iteration=ev.iteration,
        )
        u.history.append(_change(ev, None, "active"))
        s.uncertainties[uid] = u
        return
    u.occurrences += 1
    u.last_seen_iteration = ev.iteration
    if u.status == "resolved":
        u.status = "active"
        u.history.append(_change(ev, "resolved", "active", reason="reported again"))


def _uncertainty_resolved(s: ResearchState, ev: StateEvent) -> None:
    (uid,) = _need(ev, "uncertainty_id")
    u = s.uncertainties.get(uid)
    if u is None or u.status != "active":
        raise StateIntegrityError(f"{ev.event_id}: uncertainty {uid} is not active")
    u.status = "resolved"
    u.history.append(_change(ev, "active", "resolved", reason=_get(ev, "reason", "")))


def _model_version_observed(s: ResearchState, ev: StateEvent) -> None:
    (name,) = _need(ev, "name")
    rec = s.model_versions.get(name) or ModelVersionRecord(
        name=name, first_seen_iteration=ev.iteration
    )
    component = _get(ev, "component")
    if component and component not in rec.components:
        rec.components.append(component)
    rec.last_seen_iteration = ev.iteration
    rec.occurrences += 1
    s.model_versions[name] = rec


HANDLERS: dict[str, Callable[[ResearchState, StateEvent], None]] = {
    "objective_set": _objective_set,
    "iteration_advanced": _iteration_advanced,
    "candidate_registered": _candidate_registered,
    "ranking_recorded": _ranking_recorded,
    "candidate_status_update": _candidate_status_update,
    "hypothesis_registered": _hypothesis_registered,
    "hypothesis_update": _hypothesis_update,
    "experiment_planned": _experiment_planned,
    "experiment_failed": _experiment_failed,
    "result_recorded": _result_recorded,
    "finding_recorded": _finding_recorded,
    "relationship_observed": _relationship_observed,
    "evidence_recorded": _evidence_recorded,
    "question_opened": _question_opened,
    "question_closed": _question_closed,
    "uncertainty_observed": _uncertainty_observed,
    "uncertainty_resolved": _uncertainty_resolved,
    "model_version_observed": _model_version_observed,
}


def apply_event(state: ResearchState, event: StateEvent) -> None:
    """Validate ``event`` against ``state`` and apply it in place."""
    if event.seq != state.event_count + 1:
        raise StateIntegrityError(
            f"{event.event_id}: expected seq {state.event_count + 1}, got {event.seq}"
        )
    if event.prev_hash != state.last_event_hash:
        raise StateIntegrityError(
            f"{event.event_id}: prev_hash does not continue the log (history was altered)"
        )
    if event.event_hash != hash_event(event.model_dump(mode="json")):
        raise StateIntegrityError(
            f"{event.event_id}: content does not match its hash (event was edited)"
        )
    handler = HANDLERS.get(event.event)
    if handler is None:
        raise StateIntegrityError(f"{event.event_id}: unknown event type {event.event!r}")
    handler(state, event)
    state.event_count = event.seq
    state.last_event_hash = event.event_hash


def replay(
    events: Iterable[StateEvent],
    *,
    upto_iteration: int | None = None,
    upto_event_count: int | None = None,
) -> ResearchState:
    """Rebuild the state from scratch.

    ``upto_iteration=k`` gives the state after loop turn ``k`` closed; ``upto_event_count=n`` gives
    the state after exactly the first ``n`` events (finer-grained: e.g. *before* a given analysis).
    """
    state = ResearchState()
    for ev in events:
        if upto_iteration is not None and ev.iteration > upto_iteration:
            break
        if upto_event_count is not None and ev.seq > upto_event_count:
            break
        apply_event(state, ev)
    return state


__all__ = ["DECISIVE_RELATIONSHIPS", "HANDLERS", "apply_event", "relationship_key", "replay"]
