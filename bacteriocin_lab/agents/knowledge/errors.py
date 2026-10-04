"""Errors raised by the state manager. The Omnigent-facing agent turns each into a structured envelope."""

from __future__ import annotations


class KnowledgeError(Exception):
    """Base class."""


class StateInputError(KnowledgeError):
    """The caller's input cannot be turned into valid state events."""


class StateConflict(KnowledgeError):
    """The write would silently overwrite or contradict recorded history, or the state moved underneath it."""


class StateIntegrityError(KnowledgeError):
    """The event log is inconsistent: a broken hash chain, a skipped sequence number, or an impossible transition."""


class NotFound(KnowledgeError):
    """A requested candidate, hypothesis or experiment is not in the state."""
