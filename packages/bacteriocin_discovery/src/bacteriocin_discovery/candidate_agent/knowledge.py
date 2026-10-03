"""Pluggable knowledge sources for known bacteriocins.

Contract rule 6 forbids hidden state that Omnigent cannot reconstruct, which
rules out a knowledge base baked into the agent's code path. So:

* The agent's primary input is the ``evidence`` and ``candidate_pool`` that
  Omnigent passes in.
* A ``KnowledgeSource`` is *injected* at construction. The agent reports which
  source it used and how many records it drew, so a run can be reconstructed.
* The shipped seed file is an example dataset for tests and demos, not an
  authority.

ON THE SEED DATA
----------------
``data/seed_bacteriocins.json`` carries ``"sequence_verified": false`` on every
record, because the sequences were transcribed from secondary knowledge rather
than fetched from a primary database. Any record used with
``sequence_verified: false`` produces a warning on the agent's output. Run
``scripts/verify_seed_sequences.py`` to check them against UniProt and flip the
flag. Do not treat an unverified sequence as publication-grade.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_SEED_PATH = Path(__file__).resolve().parent.parent / "data" / "seed_bacteriocins.json"


class KnowledgeRecord(BaseModel):
    """One curated bacteriocin entry from a knowledge source."""

    model_config = ConfigDict(extra="allow")

    name: str
    sequence: str | None = None
    origin: str = Field(default="database", description="'literature' or 'database'.")
    bacteriocin_class: str | None = None
    producing_organism: str | None = None
    known_targets: list[str] = Field(default_factory=list)
    known_non_targets: list[str] = Field(default_factory=list)
    structural_features: list[str] = Field(default_factory=list)
    known_stability: dict[str, Any] = Field(default_factory=dict)
    environmental_sensitivity: list[str] = Field(default_factory=list)
    resistance_concerns: list[str] = Field(default_factory=list)
    receptor: str | None = None
    accession: str | None = Field(default=None, description="UniProt/BACTIBASE accession.")
    source: str | None = Field(default=None, description="Citation or database name.")
    sequence_verified: bool = Field(
        default=False, description="True only if checked against a primary database."
    )
    notes: str | None = None


@runtime_checkable
class KnowledgeSource(Protocol):
    """Anything that can yield curated bacteriocin records.

    Implement this to plug in BACTIBASE, BAGEL4, an internal curation store, or
    a live retrieval agent, without touching the agent.
    """

    @property
    def source_name(self) -> str:
        """Identifier recorded in the agent's provenance output."""
        ...

    def records(self) -> list[KnowledgeRecord]:
        """Return all available records."""
        ...


class InMemoryKnowledgeSource:
    """Knowledge source over an explicit in-memory list. Useful in tests."""

    def __init__(self, records: list[KnowledgeRecord] | list[dict[str, Any]], *, name: str):
        self._records = [
            r if isinstance(r, KnowledgeRecord) else KnowledgeRecord.model_validate(r)
            for r in records
        ]
        self._name = name

    @property
    def source_name(self) -> str:
        return self._name

    def records(self) -> list[KnowledgeRecord]:
        return list(self._records)


class JsonFileKnowledgeSource:
    """Knowledge source backed by a JSON file.

    The file must be a JSON array of objects matching ``KnowledgeRecord``.
    Records are loaded once and cached; the file is not watched.
    """

    def __init__(self, path: str | Path, *, name: str | None = None):
        self._path = Path(path)
        self._name = name or f"json:{self._path.name}"
        self._cache: list[KnowledgeRecord] | None = None

    @property
    def source_name(self) -> str:
        return self._name

    def records(self) -> list[KnowledgeRecord]:
        if self._cache is None:
            if not self._path.is_file():
                raise FileNotFoundError(f"Knowledge file not found: {self._path}")
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{self._path} is not valid JSON: {exc}") from exc
            if not isinstance(raw, list):
                raise ValueError(f"{self._path} must contain a JSON array, got {type(raw).__name__}")
            self._cache = [KnowledgeRecord.model_validate(entry) for entry in raw]
        return list(self._cache)


class EmptyKnowledgeSource:
    """No curated records. The agent then works purely from supplied input."""

    @property
    def source_name(self) -> str:
        return "empty"

    def records(self) -> list[KnowledgeRecord]:
        return []


def default_knowledge_source() -> KnowledgeSource:
    """The shipped seed dataset, or an empty source if it is missing.

    Falling back to empty rather than raising keeps the agent callable in a
    deployment that supplies its own candidate pool and never needs the seed.
    """
    if DEFAULT_SEED_PATH.is_file():
        return JsonFileKnowledgeSource(DEFAULT_SEED_PATH, name="seed_bacteriocins.json")
    return EmptyKnowledgeSource()


__all__ = [
    "DEFAULT_SEED_PATH",
    "EmptyKnowledgeSource",
    "InMemoryKnowledgeSource",
    "JsonFileKnowledgeSource",
    "KnowledgeRecord",
    "KnowledgeSource",
    "default_knowledge_source",
]
