"""Autonomous bacteriocin-discovery lab: evidence, candidate design, simulated experiments.

Layout:

* ``shared``        -- schemas, enums, ids and config used by every agent
* ``agents``        -- the specialists (evidence, candidate, planner, simulator,
  analysis, knowledge, critic); agents never import each other
* ``adapters``      -- experiment backends behind one API (simulation, wet lab stub)
* ``orchestration`` -- workflow, routing and the Omnigent adapter; the only layer
  that sees more than one agent
* ``evaluation``    -- benchmarks and demo scenarios
"""

__version__ = "0.1.0"
