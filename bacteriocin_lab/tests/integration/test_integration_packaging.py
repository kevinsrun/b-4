"""Packaging and import correctness: tests 1, 2, 3, 27, 28.

Everything here runs in a fresh interpreter from a directory outside the repository, so nothing can
pass because of the current working directory, pytest's ``pythonpath`` or an IDE environment.
"""

from __future__ import annotations

import ast
import glob
import importlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
PACKAGE_DIR = REPO / "bacteriocin_lab"


def python(code: str, cwd: Path, **kwargs):
    return subprocess.run(
        [sys.executable, "-c", code], cwd=cwd, capture_output=True, text=True, timeout=120, **kwargs
    )


# --------------------------------------------------------------------------- TEST 1
def test_01_clean_package_import_needs_no_path_tricks(tmp_path):
    proc = python(
        "import sys; before = list(sys.path); import bacteriocin_lab; "
        "assert sys.path == before, 'importing the package changed sys.path'; "
        "print(bacteriocin_lab.__file__)",
        tmp_path,
    )
    assert proc.returncode == 0, proc.stderr
    assert Path(proc.stdout.strip()).resolve().is_relative_to(REPO), (
        "imported from outside the repo"
    )


def test_01_no_module_mutates_sys_path_or_cwd():
    """No library module may rely on, or change, the interpreter's path or working directory."""
    offenders = []
    for path in PACKAGE_DIR.rglob("*.py"):
        rel = path.relative_to(PACKAGE_DIR)
        if rel.parts[0] == "tests" or "examples" in rel.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                target = ast.unparse(node.func)
                if target in {"sys.path.insert", "sys.path.append", "os.chdir"}:
                    offenders.append(f"{rel}:{node.lineno} {target}")
    assert not offenders, offenders


# --------------------------------------------------------------------------- TEST 2
AGENT_INTERFACES = {
    "1 evidence": ("bacteriocin_lab.agents.evidence", ["LiteratureEvidenceAgent"]),
    "2 candidate": (
        "bacteriocin_lab.agents.candidate",
        ["generate_candidates", "CandidateGenerationAgent"],
    ),
    "3 planner": ("bacteriocin_lab.agents.planner", ["run_agent", "ExperimentPlanner"]),
    "4 simulator": (
        "bacteriocin_lab.agents.simulator",
        ["run_experiment", "run_experiments", "run_agent", "SimulationAgent"],
    ),
    "5 analysis": (
        "bacteriocin_lab.agents.analysis",
        ["analyze_result", "ResultAnalysisAgent"],
    ),
    "6 knowledge": ("bacteriocin_lab.agents.knowledge", ["KnowledgeAgent", "knowledge_call"]),
    "7 critic": (
        "bacteriocin_lab.agents.critic",
        ["run_agent", "review_claim", "ScientificCriticAgent"],
    ),
    "8 orchestration": (
        "bacteriocin_lab.orchestration",
        ["run_discovery", "OmnigentAdapter", "AgentRegistry", "DiscoveryWorkflowEngine"],
    ),
}


@pytest.mark.parametrize("agent", AGENT_INTERFACES)
def test_02_every_agent_imports_and_exposes_its_public_interface(agent, tmp_path):
    module, names = AGENT_INTERFACES[agent]
    mod = importlib.import_module(module)
    for name in names:
        assert callable(getattr(mod, name)), f"{module}.{name} is missing or not callable"
    # And from a fresh interpreter outside the repo, with no live API required.
    proc = python(
        f"import {module} as m; assert all(callable(getattr(m, n)) for n in {names!r})", tmp_path
    )
    assert proc.returncode == 0, proc.stderr


def test_02_every_submodule_imports():
    import pkgutil

    import bacteriocin_lab

    failures = []
    for info in pkgutil.walk_packages(bacteriocin_lab.__path__, "bacteriocin_lab."):
        if ".tests." in info.name or info.name.endswith(".tests") or "examples" in info.name:
            continue
        try:
            importlib.import_module(info.name)
        except ModuleNotFoundError as exc:
            # A transport that names its own missing optional extra is not a packaging defect.
            if info.name.endswith(".mcp_server") and "mcp" in str(exc):
                continue
            failures.append(f"{info.name}: {exc}")
        except Exception as exc:  # report all failures, not only the first
            failures.append(f"{info.name}: {type(exc).__name__}: {exc}")
    assert not failures, "\n".join(failures)


# --------------------------------------------------------------------------- TEST 3
def roundtrip(model_cls, instance):
    """JSON-compatible dump -> real JSON text -> validate -> identical dump."""
    dumped = instance.model_dump(mode="json")
    revived = model_cls.model_validate(json.loads(json.dumps(dumped)))
    assert revived.model_dump(mode="json") == dumped
    return revived


def test_03_shared_schemas_roundtrip_with_semantic_equality():
    from bacteriocin_lab.agents.critic import CriticReview
    from bacteriocin_lab.agents.critic import run_agent as critic_run
    from bacteriocin_lab.agents.knowledge import initialize_state
    from bacteriocin_lab.agents.simulator import run_experiment
    from bacteriocin_lab.agents.simulator.schemas import ExperimentResult, ExperimentSpec
    from bacteriocin_lab.agents.simulator.selftest import spec as sim_spec
    from bacteriocin_lab.orchestration import ResearchObjective, ResearchState
    from bacteriocin_lab.orchestration.types import Candidate, Finding, Hypothesis
    from bacteriocin_lab.shared import ResearchState as KnowledgeState

    roundtrip(
        ResearchObjective,
        ResearchObjective(
            goal="g", target={"species": "Listeria monocytogenes"}, desired_behavior={"ph": 7.0}
        ),
    )
    roundtrip(
        Candidate,
        Candidate(candidate_id="cand_1", name="B17", sequence="ITSISLCTPGCK", confidence=0.4),
    )
    roundtrip(
        Hypothesis,
        Hypothesis(
            hypothesis_id="hyp_1", candidate_id="cand_1", statement="s", prior_plausibility=0.3
        ),
    )
    spec = roundtrip(ExperimentSpec, ExperimentSpec.model_validate(sim_spec()))
    result = roundtrip(ExperimentResult, run_experiment(sim_spec()))
    assert result.evidence_type.value == "simulation-derived"
    assert result.validated_experimentally is False
    roundtrip(
        Finding,
        Finding(
            finding_id="find_1",
            statement="s",
            status="supported",
            confidence=0.8,
            candidate_ids=["cand_1"],
            hypothesis_ids=["hyp_1"],
            evidence_ids=[result.result_id],
        ),
    )

    review_env = critic_run(
        {
            "claims": [
                {
                    "claim_id": "c1",
                    "statement": "s",
                    "result_ids": [result.result_id],
                    "candidate_id": result.candidate_id,
                }
            ],
            "previous_results": [result.to_json_dict()],
        }
    ).model_dump(mode="json")
    roundtrip(CriticReview, CriticReview.model_validate(review_env["artifacts"]["review"]))

    roundtrip(
        KnowledgeState, initialize_state({"goal": "g", "target": "Listeria monocytogenes"}).state
    )

    from bacteriocin_lab.tests.integration.helpers import run

    state = ResearchState.model_validate(run(max_iterations=2).final_state)
    roundtrip(ResearchState, state)
    assert spec.experiment_id == sim_spec()["experiment_id"]


# -------------------------------------------------------------------------- TEST 27
def test_27_fresh_install_smoke(tmp_path):
    """Install the project into an empty prefix (a non-editable wheel build of a pristine copy), then
    import and run the demo from a neutral directory against that installed copy only."""
    pytest.importorskip(
        "setuptools", reason="building the wheel offline needs setuptools in this env"
    )
    from importlib import metadata

    def installed():
        try:
            return metadata.distribution("bacteriocin-lab").version
        except metadata.PackageNotFoundError:
            return None

    before = installed()
    src = tmp_path / "src"
    shutil.copytree(
        REPO,
        src,
        ignore=shutil.ignore_patterns(
            ".git", "build", "dist", "*.egg-info", "__pycache__", ".pytest_cache", ".venv", "*.yaml"
        ),
    )
    prefix = tmp_path / "prefix"
    install = subprocess.run(
        # --ignore-installed matters: without it pip sees the developer's own (editable) install of the
        # same project, uninstalls it first, and this test would silently wreck the environment.
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--no-build-isolation",
            "--no-index",
            "--ignore-installed",
            "--quiet",
            "--prefix",
            str(prefix),
            str(src),
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert install.returncode == 0, install.stdout + install.stderr
    assert installed() == before, "the smoke test altered the developer's own environment"
    site = glob.glob(str(prefix / "lib" / "python*" / "site-packages"))
    assert site, "install produced no site-packages"

    work = tmp_path / "elsewhere"
    work.mkdir()
    env = {"PYTHONPATH": site[0], "PATH": "/usr/bin:/bin"}
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import bacteriocin_lab, sys; print(bacteriocin_lab.__file__);"
            "from bacteriocin_lab.agents.candidate import default_knowledge_source as k;"
            "assert k().__class__.__name__ != 'EmptyKnowledgeSource', 'package data missing from wheel'",
        ],
        cwd=work,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert probe.returncode == 0, probe.stderr
    assert Path(probe.stdout.strip()).resolve().is_relative_to(prefix.resolve()), probe.stdout

    demo = subprocess.run(
        [sys.executable, "-m", "bacteriocin_lab"],
        cwd=work,
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
    )
    assert demo.returncode == 0, demo.stdout[-500:] + demo.stderr[-500:]
    assert "DEMO COMPLETED SUCCESSFULLY" in demo.stdout


# -------------------------------------------------------------------------- TEST 28
@pytest.mark.parametrize("module", ["bacteriocin_lab", "bacteriocin_lab.evaluation.demo_scenarios"])
def test_28_demo_entry_point_runs_from_anywhere(module, tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", module], cwd=tmp_path, capture_output=True, text=True, timeout=300
    )
    assert proc.returncode == 0, proc.stdout[-500:] + proc.stderr[-500:]
    assert "DEMO COMPLETED SUCCESSFULLY" in proc.stdout
    assert "evidence_added" in proc.stdout, "demo no longer records literature evidence"
