"""TEST 15 & Omnigent Adapter test.

Verifies the Omnigent adapter methods (run, inspect_state, inspect_trace, resume, save/load)
and executes the demo entry point.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from bacteriocin_lab.evaluation.demo_scenarios import run_demo
from bacteriocin_lab.orchestration import OmnigentAdapter, ResearchObjective
from bacteriocin_lab.orchestration.registry import AgentRegistry


def test_omnigent_adapter_full_lifecycle() -> None:
    adapter = OmnigentAdapter(registry=AgentRegistry.fixture())

    objective = ResearchObjective(
        goal="Omnigent adapter lifecycle test.",
        target={"species": "Listeria monocytogenes"},
    )

    # 1. Run campaign through adapter
    result = adapter.run(objective=objective, max_iterations=1, seed=42)
    assert result.run_id is not None
    assert result.status in ("completed", "max_iterations")

    # 2. Inspect state
    state_dict = adapter.inspect_state(result.run_id)
    assert state_dict is not None
    assert state_dict["iteration"] == 1
    assert len(state_dict["candidates"]) >= 1

    # 3. Inspect trace
    trace = adapter.inspect_trace(result.run_id)
    assert trace is not None
    assert len(trace) >= 1
    assert trace[0]["agent"] == "evidence"

    # 4. Resume campaign
    resumed = adapter.resume(result.run_id, additional_iterations=1)
    assert resumed.iterations_completed == 2
    resumed_state = adapter.inspect_state(resumed.run_id)
    assert resumed_state["iteration"] == 2

    # 5. Save and load state from file
    with tempfile.TemporaryDirectory() as tmp_dir:
        state_file = Path(tmp_dir) / "state.json"
        active_state = adapter._states[resumed.run_id]
        adapter.save_state_to_file(active_state, state_file)
        assert state_file.is_file()

        loaded_state = adapter.load_state_from_file(state_file)
        assert loaded_state.iteration == active_state.iteration
        assert len(loaded_state.candidates) == len(active_state.candidates)


def test_demo_entry_point_executes() -> None:
    """Executes the demo function verifying fresh-clone style demo invocation."""
    ret = run_demo()
    assert ret == 0
