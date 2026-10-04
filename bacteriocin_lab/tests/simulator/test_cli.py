"""CLI tests: the reproducible, scriptable entry point."""

from __future__ import annotations

import json

import pytest

from bacteriocin_lab.agents.simulator.cli import main
from bacteriocin_lab.agents.simulator.selftest import spec


@pytest.fixture
def spec_file(tmp_path):
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec(experiment_id="cli-1")), encoding="utf-8")
    return str(path)


def test_capabilities_emits_json(capsys) -> None:
    assert main(["capabilities"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["backends"]["simulation"]["available"] is True


@pytest.mark.parametrize(
    "name", ["experiment_spec", "experiment_result", "agent_input", "agent_output", "all"]
)
def test_schema_emits_valid_json_schema(capsys, name: str) -> None:
    assert main(["schema", name]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload


def test_unknown_schema_is_rejected(capsys) -> None:
    assert main(["schema", "nonsense"]) == 2


def test_run_emits_a_result(capsys, spec_file: str) -> None:
    assert main(["run", "--spec", spec_file]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["evidence_type"] == "simulation-derived"


def test_compact_flag_works_after_the_subcommand(capsys, spec_file: str) -> None:
    assert main(["run", "--spec", spec_file, "--compact"]) == 0
    out = capsys.readouterr().out.strip()
    assert "\n" not in out


def test_compact_flag_works_before_the_subcommand(capsys, spec_file: str) -> None:
    assert main(["--compact", "run", "--spec", spec_file]) == 0
    assert "\n" not in capsys.readouterr().out.strip()


def test_batch_run_returns_one_result_per_spec(capsys, tmp_path) -> None:
    path = tmp_path / "specs.json"
    path.write_text(
        json.dumps([spec(experiment_id="a"), spec(experiment_id="b", conditions={"ph": 5.0})]),
        encoding="utf-8",
    )
    assert main(["run", "--spec", str(path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [r["experiment_id"] for r in payload] == ["a", "b"]


def test_batch_with_a_failure_exits_nonzero(capsys, tmp_path) -> None:
    path = tmp_path / "specs.json"
    path.write_text(
        json.dumps([spec(experiment_id="a"), {"experiment_id": "bad", "conditions": {"ph": 99}}]),
        encoding="utf-8",
    )
    assert main(["run", "--spec", str(path)]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload[1]["status"] == "failed"


def test_sweep_produces_a_monotone_dose_response(capsys, spec_file: str) -> None:
    assert main(
        ["sweep", "--spec", spec_file, "--factor", "bacteriocin_concentration",
         "--values", "0.05,0.2,0.5,1,5", "--unit", "uM"]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    inhibitions = [p["predicted_inhibition_fraction"] for p in payload["points"]]
    assert inhibitions == sorted(inhibitions)
    assert payload["validated_experimentally"] is False


def test_sweep_over_cell_density_is_supported(capsys, spec_file: str) -> None:
    assert main(
        ["sweep", "--spec", spec_file, "--factor", "target_cell_density",
         "--values", "1e4,1e6,1e8", "--unit", "cfu_per_ml"]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["points"]) == 3


def test_sweep_rejects_non_numeric_values(capsys, spec_file: str) -> None:
    assert main(["sweep", "--spec", spec_file, "--values", "a,b"]) == 2


def test_agent_command_emits_the_envelope(capsys, tmp_path) -> None:
    path = tmp_path / "envelope.json"
    path.write_text(
        json.dumps({"experiment_specs": [spec(experiment_id="agent-1")]}), encoding="utf-8"
    )
    assert main(["agent", "--input", str(path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["agent"] == "simulation_experiment_backend"


def test_selftest_passes(capsys) -> None:
    assert main(["selftest"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is True
    assert payload["n_failed"] == 0


def test_missing_file_is_reported_not_crashed() -> None:
    assert main(["run", "--spec", "/nonexistent/path.json"]) == 2


def test_malformed_json_is_reported_not_crashed(tmp_path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    assert main(["run", "--spec", str(path)]) == 2
