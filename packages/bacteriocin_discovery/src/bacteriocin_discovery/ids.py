"""Persistent, reproducible ID generation.

Contract rule 7 requires persistent IDs for scientific entities and rule 13
requires reproducible output where deterministic computation is possible. These
two together rule out random UUIDs for anything derived from content: re-running
the agent on the same input must produce the same ``candidate_id`` so that
results accumulated across loop iterations stay joinable.

IDs are therefore content-addressed: a short BLAKE2b digest of the canonical
JSON of the identifying fields. Two different runs that describe the same
scientific entity converge on the same ID; two different entities effectively
never collide (16 hex chars = 64 bits, so a birthday collision needs ~5e9
entities).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

#: Length of the hex digest suffix. 16 hex chars = 64 bits.
_DIGEST_CHARS = 16

_PREFIXES = {
    "candidate": "cand",
    "experiment": "exp",
    "evidence": "ev",
    "hypothesis": "hyp",
    "result": "res",
    "finding": "find",
    "run": "run",
    "review": "rev",
}


def _canonical(payload: Any) -> str:
    """Serialise ``payload`` so that equal content always yields equal bytes."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=True)


def content_id(kind: str, payload: Any, *, namespace: str = "bacteriocin-discovery/v1") -> str:
    """Return a deterministic ID of the form ``<prefix>_<16 hex chars>``.

    Args:
        kind: One of the keys in ``_PREFIXES`` ("candidate", "hypothesis", ...).
        payload: The identifying content. Only include fields that genuinely
            identify the entity -- including a timestamp here would destroy
            reproducibility.
        namespace: Changed only if the ID scheme itself is revised, so that a
            future scheme cannot collide with this one.

    Raises:
        ValueError: If ``kind`` is not a known entity kind.
    """
    try:
        prefix = _PREFIXES[kind]
    except KeyError:
        raise ValueError(
            f"Unknown entity kind {kind!r}; expected one of {sorted(_PREFIXES)}"
        ) from None

    digest = hashlib.blake2b(
        f"{namespace}|{kind}|{_canonical(payload)}".encode(), digest_size=16
    ).hexdigest()[:_DIGEST_CHARS]
    return f"{prefix}_{digest}"


def candidate_id(*, sequence: str | None, name: str | None, origin: str) -> str:
    """ID for a bacteriocin candidate.

    Keyed on the sequence when there is one, because the sequence *is* the
    scientific identity: the same peptide reached by two routes should be one
    candidate. Named entries with no sequence fall back to the name.
    """
    if sequence:
        key: dict[str, Any] = {"sequence": sequence.strip().upper()}
    elif name:
        key = {"name": name.strip().lower(), "origin": origin}
    else:
        raise ValueError("A candidate needs at least a sequence or a name to be identified")
    return content_id("candidate", key)


def hypothesis_id(*, candidate: str, target_species: str, prediction: str) -> str:
    """ID for a testable hypothesis about one candidate against one target."""
    return content_id(
        "hypothesis",
        {
            "candidate": candidate,
            "target_species": target_species.strip().lower(),
            "prediction": prediction.strip(),
        },
    )


def evidence_id(*, claim: str, source: str | None, evidence_type: str) -> str:
    """ID for a provenance record."""
    return content_id(
        "evidence",
        {"claim": claim.strip(), "source": (source or "").strip(), "evidence_type": evidence_type},
    )


def finding_id(*, experiment_id: str, hypothesis_id: str | None, result_id: str, model_version: str) -> str:
    """ID for one analysis of one result against one hypothesis.

    Includes ``model_version`` so a re-analysis by changed logic is a new finding
    rather than silently overwriting the old interpretation.
    """
    return content_id(
        "finding",
        {
            "experiment_id": experiment_id,
            "hypothesis_id": hypothesis_id or "",
            "result_id": result_id,
            "model_version": model_version,
        },
    )


def run_id(payload: Any) -> str:
    """ID for one invocation of an agent, keyed on its full request."""
    return content_id("run", payload)


__all__ = ["candidate_id", "content_id", "evidence_id", "finding_id", "hypothesis_id", "run_id"]
