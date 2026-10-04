"""Public, human-readable views over internal discovery state.

The scientific workflow keeps its complete typed state and provenance.  This
package is deliberately a one-way boundary for the product surface: it turns
that state into concise language without changing its scientific meaning.
"""

from .discovery import build_discovery_response, infer_target

__all__ = ["build_discovery_response", "infer_target"]
